from odoo import models, fields


class BlogPost(models.Model):
    _inherit = 'blog.post'

    proposal_id = fields.Many2one(
        'ai.blog.proposal',
        string='AI Proposal',
        readonly=True,
        ondelete='set null',
    )
