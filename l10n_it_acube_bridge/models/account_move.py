from odoo import models, fields


class AccountMove(models.Model):
    _inherit = 'account.move'

    acube_source = fields.Selection(
        selection=[
            ('manual', 'Manuale'),
            ('sdi', 'Ricevuta da SDI'),
            ('pdf_import', 'Importata da PDF'),
        ],
        string='Origine A-Cube',
        copy=False,
        readonly=True,
    )
