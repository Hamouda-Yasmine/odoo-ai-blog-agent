import json
import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiBlogProposal(models.Model):
    _name = 'ai.blog.proposal'
    _description = 'AI Blog Proposal'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'title'
    _order = 'relevance_score desc, create_date desc'

    title = fields.Char(string='Suggested Title', required=True, tracking=True)
    summary = fields.Text(string='Subject Summary')
    context_identified = fields.Text(string='Identified Context')
    editorial_angle = fields.Text(string='Editorial Angle')
    sources = fields.Text(string='Potential Sources')
    relevance_score = fields.Float(string='Relevance Score', digits=(3, 1))
    relevance_justification = fields.Text(string='Selection Justification')

    cover_image = fields.Image(
        string='Cover Image',
        max_width=1920,
        max_height=1080,
        help='Cover image for the generated blog article',
    )
    cover_image_alt = fields.Char(
        string='Cover Image Alt Text',
        help='Leave empty to auto-generate from title and keywords',
    )

    domain_id = fields.Many2one('ai.blog.domain', string='Domain', required=True)
    extra_instructions = fields.Text(string='Additional Instructions for Writer')

    blog_id = fields.Many2one('blog.blog', string='Target Blog')
    blog_post_ids = fields.One2many('blog.post', 'proposal_id', string='Generated Articles')
    blog_post_count = fields.Integer(compute='_compute_blog_post_count')

    state = fields.Selection([
        ('pending', 'Pending Validation'),
        ('validated', 'Validated'),
        ('rejected', 'Rejected'),
    ], default='pending', string='Status', tracking=True, required=True)

    @api.depends('blog_post_ids')
    def _compute_blog_post_count(self):
        for rec in self:
            rec.blog_post_count = len(rec.blog_post_ids)

    def action_validate(self):
        for rec in self:
            rec.state = 'validated'
            rec.message_post(body=_('Proposal validated.'))

    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'
            rec.message_post(body=_('Proposal rejected.'))

    def action_view_blog_posts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Articles'),
            'res_model': 'blog.post',
            'view_mode': 'list,form',
            'domain': [('proposal_id', '=', self.id)],
        }

    def action_generate_article(self):
        self.ensure_one()

        provider = self.env['ai.blog.provider'].search(
            [('is_default', '=', True), ('active', '=', True)], limit=1
        )
        if not provider:
            provider = self.env['ai.blog.provider'].search([('active', '=', True)], limit=1)
        if not provider:
            raise UserError(_('No active AI provider configured.'))

        keyword_str = ', '.join(self.domain_id.keyword_ids.mapped('name'))
        language = (self.domain_id.language_id.code or 'en').split('_')[0]

        prompt = self._build_writer_prompt(keyword_str, language)

        _logger.info('Writer agent [%s]: calling provider "%s"', self.title, provider.name)
        try:
            raw_response = provider.call(prompt, max_tokens=8192)
        except Exception as e:
            raise UserError(_('AI provider call failed: %s') % str(e))

        article_data = self._parse_json_response(raw_response)

        blog = self.blog_id or self.env['blog.blog'].search([], limit=1)
        if not blog:
            raise UserError(_('No blog found. Please create a blog in Website first.'))

        tag_ids = []
        for tag_name in (article_data.get('tags') or []):
            tag_name = (tag_name or '').strip()
            if not tag_name:
                continue
            tag = self.env['blog.tag'].search([('name', '=ilike', tag_name)], limit=1)
            if not tag:
                tag = self.env['blog.tag'].create({'name': tag_name})
            tag_ids.append(tag.id)

        cover_image_url = f'/web/image/ai.blog.proposal/{self.id}/cover_image'

        # Resolve alt text: user field → AI suggestion → auto-generated
        alt_text = (
            self.cover_image_alt
            or article_data.get('cover_image_alt', '')
            or f'{self.title} - {keyword_str}'
        )

        blog_post_vals = {
            'name': article_data.get('title') or self.title,
            'subtitle': article_data.get('subtitle', ''),
            'blog_id': blog.id,
            'content': article_data.get('content', ''),
            'website_meta_title': (article_data.get('meta_title') or '')[:60],
            'website_meta_description': (article_data.get('meta_description') or '')[:155],
            'website_meta_keywords': article_data.get('meta_keywords', ''),
            'tag_ids': [(6, 0, tag_ids)],
            'is_published': False,
            'proposal_id': self.id,
        }

        if self.cover_image:
            blog_post_vals['cover_properties'] = json.dumps({
                'background-image': f'url({cover_image_url})',
                'background-color': 'var(--black)',
                'opacity': '0.4',
                'resize_class': 'cover_full',
            })
            blog_post_vals['website_meta_og_img'] = cover_image_url

        blog_post = self.env['blog.post'].create(blog_post_vals)

        self.message_post(body=_('Article generated by AI provider "%s".') % provider.name)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Blog Post'),
            'res_model': 'blog.post',
            'res_id': blog_post.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _build_writer_prompt(self, keyword_str, language):
        lines = [
            'You are an expert SEO blog writer.',
            f'Write a complete, high-quality, SEO-optimized blog post in language code "{language}".\n',
            f'Topic: {self.title}',
            f'Domain: {self.domain_id.name}',
            f'Keywords to include naturally: {keyword_str}',
        ]
        if self.summary:
            lines.append(f'Subject summary: {self.summary}')
        if self.context_identified:
            lines.append(f'Context: {self.context_identified}')
        if self.editorial_angle:
            lines.append(f'Editorial angle: {self.editorial_angle}')
        if self.sources:
            lines.append(f'Sources to reference: {self.sources}')
        if self.extra_instructions:
            lines.append(f'Additional instructions: {self.extra_instructions}')

        lines += [
            '\nIMPORTANT: Return ONLY a raw JSON object. No markdown, no code fences, no explanation.',
            'The JSON must have exactly these keys:',
            '{',
            '  "title": "Plain text H1 title with primary keyword — NO HTML tags",',
            '  "subtitle": "Plain text subtitle — NO HTML tags",',
            '  "meta_title": "Plain text SEO title, max 60 chars — NO HTML tags",',
            '  "meta_description": "Plain text meta description, max 155 chars — NO HTML tags",',
            '  "meta_keywords": "keyword1, keyword2, keyword3, keyword4, keyword5",',
            '  "content": "<p>Full HTML article...</p>",',
            '  "tags": ["tag1", "tag2", "tag3"]' + (',' if self.cover_image else ''),
        ] + ([
            '  "cover_image_alt": "Descriptive SEO alt text for the cover image"',
        ] if self.cover_image else []) + [
            '}',
            '\nCRITICAL JSON rules:',
            '- title, subtitle, meta_title, meta_description, meta_keywords, tags: PLAIN TEXT ONLY — zero HTML',
            '- content: HTML allowed, but ALWAYS use single quotes for HTML attributes (href=\'url\' not href="url")',
            '- Never use double quotes inside any JSON string value — they break JSON parsing',
            '\nContent requirements:',
            '- Minimum 800 words',
            '- Structure: introduction → H2 sections → H3 subsections → conclusion',
            '- Use only HTML tags in content: p, h2, h3, ul, li, strong, em',
            '- Primary keyword in title, first paragraph, and at least 2 headings',
            '- meta_title: 50-60 characters for browser tab and search results',
            '- meta_description: 150-155 characters, compelling call-to-action',
            '- meta_keywords: 5-8 comma-separated SEO keywords',
            '- tags: 3-6 short topic tags',
        ]
        return '\n'.join(lines)

    def _parse_json_response(self, raw_response):
        text = raw_response.strip()

        # Strip markdown fences
        fenced = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if fenced:
            text = fenced.group(1).strip()

        # Find outermost { ... }
        if not text.startswith('{'):
            obj_match = re.search(r'\{[\s\S]*\}', text)
            if obj_match:
                text = obj_match.group()

        # First attempt: direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Second attempt: replace unescaped double quotes inside HTML content
        # by temporarily removing the content field and extracting it separately
        try:
            content_match = re.search(r'"content"\s*:\s*"([\s\S]*?)",\s*"tags"', text)
            if content_match:
                html_content = content_match.group(1)
                placeholder = '__CONTENT_PLACEHOLDER__'
                text_no_content = text.replace(content_match.group(0),
                                               f'"content": "{placeholder}", "tags"')
                data = json.loads(text_no_content)
                data['content'] = html_content
                return data
        except Exception:
            pass

        raise UserError(
            _('Could not parse AI response as JSON.\nFirst 500 chars:\n%s')
            % raw_response[:500]
        )
