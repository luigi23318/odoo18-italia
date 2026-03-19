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
        help="Indica come la fattura è stata creata nel sistema:\n"
             "- Manuale: creata dall'utente\n"
             "- Ricevuta da SDI: importata automaticamente dal Sistema di Interscambio\n"
             "- Importata da PDF: convertita da un PDF estero tramite A-Cube AI",
    )
