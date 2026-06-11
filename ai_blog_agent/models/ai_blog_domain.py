from odoo import models, fields


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

    def _cron_run_sniffer(self):
        now = fields.Datetime.now()
        domains = self.search([('active', '=', True), ('frequency', '>', 0)])
        for domain in domains:
            if not domain.last_run or (now - domain.last_run).days >= domain.frequency:
                # --- Sniffer agent code will be here ---
                domain.last_run = now
