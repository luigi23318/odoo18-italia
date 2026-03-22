from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Motore di estrazione
    foreign_invoice_extraction_engine = fields.Selection(
        selection=[
            ('tesseract', 'Tesseract OCR locale (gratuito, privacy totale)'),
            ('acube', 'A-Cube API (cloud, estrazione AI)'),
        ],
        string='Motore di estrazione',
        default='tesseract',
        config_parameter='foreign_invoice.extraction_engine',
    )

    # --- Tesseract ---
    foreign_invoice_ocr_languages = fields.Char(
        string='Lingue OCR',
        default='ita+eng+deu+fra+spa',
        config_parameter='foreign_invoice.ocr_languages',
        help='Lingue Tesseract separate da +',
    )
    foreign_invoice_use_builtin_templates = fields.Boolean(
        string='Usa template built-in',
        default=True,
        config_parameter='foreign_invoice.use_builtin_templates',
    )
    foreign_invoice_auto_extract = fields.Boolean(
        string='Auto-estrazione al caricamento',
        default=True,
        config_parameter='foreign_invoice.auto_extract',
    )

    # --- A-Cube ---
    foreign_invoice_acube_email = fields.Char(
        string='Email A-Cube',
        config_parameter='foreign_invoice.acube_email',
    )
    foreign_invoice_acube_password = fields.Char(
        string='Password A-Cube',
        config_parameter='foreign_invoice.acube_password',
    )
    foreign_invoice_acube_environment = fields.Selection(
        selection=[
            ('sandbox', 'Sandbox (test)'),
            ('production', 'Produzione'),
        ],
        string='Ambiente A-Cube',
        default='sandbox',
        config_parameter='foreign_invoice.acube_environment',
    )
    foreign_invoice_acube_auto_send = fields.Boolean(
        string='Invio automatico dopo validazione',
        default=False,
        config_parameter='foreign_invoice.acube_auto_send',
    )

    # --- Invio SDI (Aruba Premium) ---
    foreign_invoice_sdi_active = fields.Boolean(
        string='Invio SDI attivo',
        default=False,
        config_parameter='foreign_invoice.sdi_active',
    )
    foreign_invoice_aruba_username = fields.Char(
        string='Username Aruba Premium',
        config_parameter='foreign_invoice.aruba_username',
    )
    foreign_invoice_aruba_password = fields.Char(
        string='Password Aruba Premium',
        config_parameter='foreign_invoice.aruba_password',
    )
    foreign_invoice_aruba_environment = fields.Selection(
        selection=[
            ('demo', 'Demo (test)'),
            ('production', 'Produzione'),
        ],
        string='Ambiente Aruba',
        default='demo',
        config_parameter='foreign_invoice.aruba_environment',
    )
    foreign_invoice_codice_destinatario = fields.Char(
        string='Codice destinatario',
        default='KRRH6B9',
        config_parameter='foreign_invoice.codice_destinatario',
    )
    foreign_invoice_polling_frequency = fields.Selection(
        selection=[
            ('5', '5 minuti'),
            ('15', '15 minuti'),
            ('30', '30 minuti'),
            ('60', '60 minuti'),
        ],
        string='Frequenza polling notifiche',
        default='15',
        config_parameter='foreign_invoice.polling_frequency',
    )

    def set_values(self) -> None:
        super().set_values()
        # Aggiorna frequenza cron polling
        cron = self.env.ref(
            'l10n_it_foreign_invoice_sdi.cron_sdi_notification_polling',
            raise_if_not_found=False,
        )
        if cron:
            freq = int(self.foreign_invoice_polling_frequency or 15)
            cron.write({
                'interval_number': freq,
                'active': self.foreign_invoice_sdi_active,
            })
