import json
import logging
import re
from odoo import models, fields

_logger = logging.getLogger(__name__)


class AiBlogDomain(models.Model):
    _name = 'ai.blog.domain'
    _description = 'AI Blog Domain'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Domain', required=True)
    language_id = fields.Many2one('res.lang', string='Language', required=True)
    frequency = fields.Integer(string='Frequency', default=7)
    max_proposals = fields.Integer(string='Max Proposals', default=3)
    active = fields.Boolean(default=True)
    last_run = fields.Datetime(string='Last Run', readonly=True)
    keyword_ids = fields.One2many('ai.blog.keyword', 'domain_id', string='Keywords')
    source_ids = fields.Many2many(
        'ai.blog.source',
        string='News Sources',
        default=lambda self: self.env['ai.blog.source'].search([
            ('active', '=', True),
            '|', ('api_key', '=', False), ('api_key', '=', ''),
        ]),
    )
    proposal_ids = fields.One2many('ai.blog.proposal', 'domain_id', string='Proposals')
    proposal_count = fields.Integer(compute='_compute_proposal_count', string='Proposals')

    def _compute_proposal_count(self):
        for rec in self:
            rec.proposal_count = len(rec.proposal_ids)

    def action_view_proposals(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Proposals',
            'res_model': 'ai.blog.proposal',
            'view_mode': 'list,form',
            'domain': [('domain_id', '=', self.id)],
        }

    def _run_sniffer(self):
        self.ensure_one()

        # Resolve active provider (default first, then any active one)
        provider = self.env['ai.blog.provider'].search(
            [('is_default', '=', True), ('active', '=', True)], limit=1
        )
        if not provider:
            provider = self.env['ai.blog.provider'].search(
                [('active', '=', True)], limit=1
            )
        if not provider:
            _logger.warning('AI Blog Sniffer: no active provider for domain "%s"', self.name)
            return

        keyword_names = self.keyword_ids.mapped('name')
        if not keyword_names:
            _logger.info('AI Blog Sniffer: no keywords on domain "%s", skipping', self.name)
            return

        # Take first 2 chars of locale code (en_US → en, fr_FR → fr)
        language = (self.language_id.code or 'en').split('_')[0]

        # Collect articles from all selected sources
        all_articles = []
        for source in self.source_ids:
            try:
                all_articles.extend(source.fetch_articles(keyword_names, language))
            except Exception as e:
                _logger.warning('AI Blog Sniffer: source "%s" failed: %s', source.name, e)

        if not all_articles:
            _logger.info('AI Blog Sniffer: no articles found for domain "%s"', self.name)
            return

        # Deduplicate by normalised title
        seen, unique_articles = set(), []
        for article in all_articles:
            key = article.get('title', '').lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique_articles.append(article)

        # Build prompt — cap at 50 articles to stay within token limits
        articles_text = '\n'.join(
            f"- {a['title']} (source: {a.get('source', 'unknown')})"
            for a in unique_articles[:50]
        )

        prompt = (
            f'You are a content strategist for the blog domain "{self.name}".\n'
            f'Keywords: {", ".join(keyword_names)}\n'
            f'Language: {language}\n\n'
            f'Here are recent news articles collected from various sources:\n'
            f'{articles_text}\n\n'
            f'Based on these articles, generate exactly {self.max_proposals} blog post proposals '
            f'that are relevant to the keywords and would be valuable for readers.\n\n'
            f'IMPORTANT: Return ONLY a raw JSON array. No markdown, no code fences, no explanation.\n'
            f'Keep ALL text fields short — maximum 30 words each.\n'
            f'Each object must have exactly these keys:\n'
            f'{{\n'
            f'  "title": "Concise blog post title (max 15 words)",\n'
            f'  "summary": "One sentence summary",\n'
            f'  "context_identified": "Key context in max 25 words",\n'
            f'  "editorial_angle": "Angle in max 20 words",\n'
            f'  "sources": "2-3 source names only, comma-separated",\n'
            f'  "relevance_score": 8.5,\n'
            f'  "relevance_justification": "One sentence justification"\n'
            f'}}'
        )

        try:
            raw_response = provider.call(prompt, max_tokens=8192)
        except Exception as e:
            _logger.error('AI Blog Sniffer: provider call failed for domain "%s": %s', self.name, e)
            return

        # Extract JSON — handle markdown fences, leading text, or bare arrays
        text = raw_response.strip()

        # Strategy 1: content inside ```...``` fences
        fenced = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if fenced:
            text = fenced.group(1).strip()

        # Strategy 2: find the outermost [...] if still not a clean array
        if not text.startswith('['):
            array_match = re.search(r'\[[\s\S]*\]', text)
            if array_match:
                text = array_match.group()

        try:
            proposals_data = json.loads(text)
        except json.JSONDecodeError:
            _logger.error(
                'AI Blog Sniffer: could not parse JSON for domain "%s".\nRaw response:\n%s',
                self.name, raw_response,
            )
            return

        if not isinstance(proposals_data, list):
            proposals_data = [proposals_data]

        created = 0
        for item in proposals_data[:self.max_proposals]:
            if not item.get('title'):
                continue
            self.env['ai.blog.proposal'].create({
                'title': item.get('title', ''),
                'summary': item.get('summary', ''),
                'context_identified': item.get('context_identified', ''),
                'editorial_angle': item.get('editorial_angle', ''),
                'sources': item.get('sources', ''),
                'relevance_score': float(item.get('relevance_score') or 0),
                'relevance_justification': item.get('relevance_justification', ''),
                'domain_id': self.id,
                'state': 'pending',
            })
            created += 1

        _logger.info('AI Blog Sniffer: created %d proposals for domain "%s"', created, self.name)

    def action_run_sniffer(self):
        self.ensure_one()
        self._run_sniffer()
        self.last_run = fields.Datetime.now()

    def _cron_run_sniffer(self):
        now = fields.Datetime.now()
        domains = self.search([('active', '=', True), ('frequency', '>', 0)])
        for domain in domains:
            if not domain.last_run or (now - domain.last_run).days >= domain.frequency:
                domain._run_sniffer()
                domain.last_run = now
