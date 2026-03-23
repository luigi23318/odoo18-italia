from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # === Motore di estrazione ===
    foreign_invoice_extraction_engine = fields.Selection(
        selection=[
            ('tesseract', 'Tesseract OCR (Locale)'),
            ('acube', 'A-Cube API (Cloud)'),
        ],
        string='Motore Estrazione Predefinito',
        config_parameter='l10n_it_foreign_invoice_sdi.default_extraction_engine',
        default='tesseract',
    )

    # === A-Cube API ===
    acube_api_url = fields.Char(
        string='A-Cube API URL',
        config_parameter='l10n_it_foreign_invoice_sdi.acube_api_url',
        default='https://api.acube.cloud',
    )
    acube_api_key = fields.Char(
        string='A-Cube API Key',
        config_parameter='l10n_it_foreign_invoice_sdi.acube_api_key',
    )

    # === Aruba Fatturazione Elettronica ===
    aruba_environment = fields.Selection(
        selection=[
            ('sandbox', 'Sandbox (Test)'),
            ('production', 'Produzione'),
        ],
        string='Ambiente Aruba',
        config_parameter='l10n_it_foreign_invoice_sdi.aruba_environment',
        default='sandbox',
    )
    aruba_username = fields.Char(
        string='Username Aruba',
        config_parameter='l10n_it_foreign_invoice_sdi.aruba_username',
    )
    aruba_password = fields.Char(
        string='Password Aruba',
        config_parameter='l10n_it_foreign_invoice_sdi.aruba_password',
    )

    # === Polling SDI ===
    sdi_polling_enabled = fields.Boolean(
        string='Polling SDI Automatico',
        config_parameter='l10n_it_foreign_invoice_sdi.sdi_polling_enabled',
        default=True,
    )
    sdi_polling_interval = fields.Integer(
        string='Intervallo Polling (minuti)',
        config_parameter='l10n_it_foreign_invoice_sdi.sdi_polling_interval',
        default=30,
    )

    # === Contabilità ===
    foreign_invoice_journal_id = fields.Many2one(
        'account.journal',
        string='Registro Fatture Estere',
        config_parameter='l10n_it_foreign_invoice_sdi.default_journal_id',
    )
