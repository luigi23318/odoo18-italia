from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_it_edi_pec_mode = fields.Selection(
        selection=[
            ('test', 'Test'),
            ('production', 'Produzione')
        ],
        string="Modalità PEC",
        config_parameter='l10n_it_edi_pec_bridge.mode'
    )

    l10n_it_edi_pec_address = fields.Char(
        string="Indirizzo PEC",
        config_parameter='l10n_it_edi_pec_bridge.address'
    )

    l10n_it_edi_pec_sdi_address = fields.Char(
        string="Indirizzo SDI",
        config_parameter='l10n_it_edi_pec_bridge.sdi_address'
    )

    l10n_it_edi_pec_server_out_id = fields.Many2one(
        'ir.mail_server',
        string="Server SMTP",
        config_parameter='l10n_it_edi_pec_bridge.smtp_server_id'
    )

    l10n_it_edi_pec_server_in_id = fields.Many2one(
        'fetchmail.server',
        string="Server IMAP",
        config_parameter='l10n_it_edi_pec_bridge.imap_server_id'
    )

    l10n_it_edi_pec_cleanup_mode = fields.Selection(
        selection=[
            ('keep', 'Mantieni tutto'),
            ('delete', 'Cancella subito'),
            ('delete_delay', 'Cancella dopo N giorni')
        ],
        string="Pulizia PEC",
        config_parameter='l10n_it_edi_pec_bridge.cleanup_mode'
    )

    l10n_it_edi_pec_cleanup_days = fields.Integer(
        string="Giorni conservazione",
        config_parameter='l10n_it_edi_pec_bridge.cleanup_days'
    )
