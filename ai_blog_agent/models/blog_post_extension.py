from odoo import models, fields


class BlogPost(models.Model):
    _inherit = 'blog.post'

    ai_proposal_id = fields.Many2one(
        'ai.blog.proposal',
        string='AI Proposal',
        readonly=True,
        ondelete='set null',
    )
