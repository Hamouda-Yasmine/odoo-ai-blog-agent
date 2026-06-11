import json
import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

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
        """Returns the number of proposals linked to this domain."""
        for rec in self:
            rec.proposal_count = len(rec.proposal_ids)

    @api.constrains('keyword_ids')
    def _check_keywords_required(self):
        """Ensures at least one keyword is defined before saving."""
        for rec in self:
            if not rec.keyword_ids:
                raise ValidationError(_('Domain "%s" must have at least one keyword.') % rec.name)

    def action_view_proposals(self):
        """Opens the filtered list of proposals for this domain."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Proposals',
            'res_model': 'ai.blog.proposal',
            'view_mode': 'list,form',
            'domain': [('domain_id', '=', self.id)],
        }

    def _run_sniffer(self):
        """Core Sniffer logic: fetches news via sources or provider web search, calls the AI, and persists proposals."""
        self.ensure_one()

        provider = self.env['ai.blog.provider'].search(
            [('is_default', '=', True), ('active', '=', True)], limit=1
        )
        if not provider:
            provider = self.env['ai.blog.provider'].search([('active', '=', True)], limit=1)
        if not provider:
            _logger.warning('AI Blog Sniffer: no active provider for domain "%s"', self.name)
            return

        keyword_names = self.keyword_ids.mapped('name')
        if not keyword_names:
            _logger.info('AI Blog Sniffer: no keywords on domain "%s", skipping', self.name)
            return

        language = (self.language_id.code or 'en').split('_')[0]

        search_payload = None
        unique_articles = []

        if provider.supports_web_search:
            _logger.info(
                'AI Blog Sniffer: domain "%s" — using provider web search (%s)',
                self.name, provider.name,
            )
            # Provider searches the web itself — skip source fetching entirely
            if provider.search_tool_payload:
                try:
                    search_payload = json.loads(provider.search_tool_payload)
                except json.JSONDecodeError:
                    _logger.warning(
                        'AI Blog Sniffer: invalid search_tool_payload JSON on provider "%s"',
                        provider.name,
                    )
        else:
            _logger.info(
                'AI Blog Sniffer: domain "%s" — using %d configured source(s)',
                self.name, len(self.source_ids),
            )
            # Fetch articles from the domain's configured sources
            all_articles = []
            for source in self.source_ids:
                try:
                    all_articles.extend(source.fetch_articles(keyword_names, language))
                except Exception as e:
                    _logger.warning('AI Blog Sniffer: source "%s" failed: %s', source.name, e)

            if not all_articles:
                _logger.info('AI Blog Sniffer: no articles found for domain "%s"', self.name)
                return

            seen = set()
            for article in all_articles:
                key = article.get('title', '').lower().strip()
                if key and key not in seen:
                    seen.add(key)
                    unique_articles.append(article)

        prompt = self._build_sniffer_prompt(
            keyword_names, language, unique_articles, provider.supports_web_search
        )

        try:
            raw_response = provider.call(prompt, max_tokens=8192, search_payload=search_payload)
        except Exception as e:
            _logger.error('AI Blog Sniffer: provider call failed for domain "%s": %s', self.name, e)
            return

        # Extract JSON — handle markdown fences, leading text, or bare arrays
        text = raw_response.strip()

        fenced = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if fenced:
            text = fenced.group(1).strip()

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

    def _build_sniffer_prompt(self, keywords, language, articles, use_web_search):
        """Builds the AI prompt for proposal generation, branching on web search vs. source articles."""
        keyword_str = ', '.join(keywords)
        header = (
            f'You are a content strategist for the blog domain "{self.name}".\n'
            f'Keywords: {keyword_str}\n'
            f'Language: {language}\n\n'
        )

        if use_web_search:
            task = (
                f'Search the web for recent news about: {keyword_str}.\n'
                f'Based on what you find, generate exactly {self.max_proposals} blog post proposals.\n\n'
            )
            articles_section = ''
        else:
            articles_text = '\n'.join(
                f"- {a['title']} (source: {a.get('source', 'unknown')})"
                for a in articles[:50]
            )
            articles_section = f'Here are recent news articles:\n{articles_text}\n\n'
            task = (
                f'Based on the provided articles, '
                f'generate exactly {self.max_proposals} blog post proposals.\n\n'
            )

        format_instructions = (
            'IMPORTANT: Return ONLY a raw JSON array. No markdown, no code fences, no explanation.\n'
            'Keep ALL text fields short — maximum 30 words each.\n'
            'Each object must have exactly these keys:\n'
            '{\n'
            '  "title": "Concise blog post title (max 15 words)",\n'
            '  "summary": "One sentence summary",\n'
            '  "context_identified": "Key context in max 25 words",\n'
            '  "editorial_angle": "Angle in max 20 words",\n'
            '  "sources": "2-3 source names only, comma-separated",\n'
            '  "relevance_score": 8.5,\n'
            '  "relevance_justification": "One sentence justification"\n'
            '}'
        )

        return header + articles_section + task + format_instructions

    def action_run_sniffer(self):
        """Manual button trigger: validates keywords are present, then runs the Sniffer."""
        self.ensure_one()
        if not self.keyword_ids:
            raise UserError(_('Please add at least one keyword to this domain before running the Sniffer.'))
        self._run_sniffer()
        self.last_run = fields.Datetime.now()

    def _cron_run_sniffer(self):
        """Scheduled action: processes all active domains whose refresh interval has elapsed."""
        now = fields.Datetime.now()
        domains = self.search([('active', '=', True), ('frequency', '>', 0)])
        for domain in domains:
            if not domain.last_run or (now - domain.last_run).days >= domain.frequency:
                domain._run_sniffer()
                domain.last_run = now
