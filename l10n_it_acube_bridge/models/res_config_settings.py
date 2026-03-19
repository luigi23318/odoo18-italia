from odoo import models, fields, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    acube_environment = fields.Selection(
        selection=[
            ('sandbox', 'Sandbox (test)'),
            ('production', 'Produzione'),
        ],
        string='Ambiente A-Cube',
        config_parameter='acube.environment',
        default='sandbox',
        help="Sandbox: ambiente di test, nessuna fattura viene inviata al SDI reale.\n"
             "Produzione: ambiente reale, le fatture vengono inviate al SDI.",
    )

    acube_email = fields.Char(
        string='Email A-Cube',
        config_parameter='acube.email',
        help="L'email utilizzata per il login alle API A-Cube.",
    )

    acube_password = fields.Char(
        string='Password A-Cube',
        config_parameter='acube.password',
        help="La password del tuo account A-Cube.",
    )

    def action_acube_test_connection(self):
        """Bottone: testa la connessione alla API A-Cube."""
        mixin = self.env['acube.mixin']
        try:
            token = mixin._acube_login()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connessione riuscita'),
                    'message': _(
                        'Login A-Cube completato con successo.\n'
                        'Ambiente: %s\nToken: %s...'
                    ) % (
                        self.acube_environment or 'sandbox',
                        token[:20] if token else '(vuoto)',
                    ),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Errore connessione A-Cube'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
