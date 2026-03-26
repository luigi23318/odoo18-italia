# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_it_edi_pec_mode = fields.Selection(
        related='company_id.l10n_it_edi_pec_mode',
        readonly=False,
    )
    l10n_it_edi_pec_server_out_id = fields.Many2one(
        related='company_id.l10n_it_edi_pec_server_out_id',
        readonly=False,
    )
    l10n_it_edi_pec_server_in_id = fields.Many2one(
        related='company_id.l10n_it_edi_pec_server_in_id',
        readonly=False,
    )
    l10n_it_edi_pec_address = fields.Char(
        related='company_id.l10n_it_edi_pec_address',
        readonly=False,
    )
    l10n_it_edi_pec_sdi_address = fields.Char(
        related='company_id.l10n_it_edi_pec_sdi_address',
        readonly=False,
    )
    l10n_it_edi_pec_cleanup_mode = fields.Selection(
        related='company_id.l10n_it_edi_pec_cleanup_mode',
        readonly=False,
    )
    l10n_it_edi_pec_cleanup_days = fields.Integer(
        related='company_id.l10n_it_edi_pec_cleanup_days',
        readonly=False,
    )
