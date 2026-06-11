from odoo import models, fields, _


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

    domain_id = fields.Many2one('ai.blog.domain', string='Domain', required=True)
    extra_instructions = fields.Text(string='Additional Instructions for Writer')

    blog_id = fields.Many2one('blog.blog', string='Target Blog')
    blog_post_id = fields.Many2one('blog.post', string='Generated Blog Post', readonly=True)

    state = fields.Selection([
        ('pending', 'Pending Validation'),
        ('validated', 'Validated'),
        ('rejected', 'Rejected'),
        ('done', 'Article Generated'),
    ], default='pending', string='Status', tracking=True, required=True)

    def action_validate(self):
        for rec in self:
            rec.state = 'validated'
            rec.message_post(body=_('Proposal validated.'))

    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'
            rec.message_post(body=_('Proposal rejected.'))

    def action_view_blog_post(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Blog Post'),
            'res_model': 'blog.post',
            'res_id': self.blog_post_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
