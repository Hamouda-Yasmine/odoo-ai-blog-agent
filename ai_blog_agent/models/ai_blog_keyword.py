from odoo import models, fields


class AiBlogKeyword(models.Model):
    _name = 'ai.blog.keyword'
    _description = 'AI Blog Keyword'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Keyword', required=True, translate=True)
    domain_id = fields.Many2one('ai.blog.domain', string='Domain', required=True, ondelete='cascade')
    active = fields.Boolean(default=True)
