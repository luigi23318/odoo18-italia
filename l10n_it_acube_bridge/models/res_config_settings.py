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
    )
    acube_email = fields.Char(
        string='Email A-Cube',
        config_parameter='acube.email',
    )
    acube_password = fields.Char(
        string='Password A-Cube',
        config_parameter='acube.password',
    )

    def action_acube_test_connection(self):
        mixin = self.env['acube.mixin']
        try:
            token = mixin._acube_login()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connessione riuscita'),
                    'message': _('Login A-Cube OK. Ambiente: %s') % (self.acube_environment or 'sandbox'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Errore connessione'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
