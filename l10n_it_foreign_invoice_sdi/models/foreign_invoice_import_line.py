from odoo import fields, models


class ForeignInvoiceImportLine(models.Model):
    _name = 'foreign.invoice.import.line'
    _description = 'Riga dettaglio fattura estera'
    _order = 'sequence, id'

    import_id = fields.Many2one(
        'foreign.invoice.import',
        string='Fattura',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='Sequenza', default=10)
    description = fields.Char(string='Descrizione')
    quantity = fields.Float(string='Quantità', default=1.0, digits=(16, 4))
    unit_price = fields.Float(string='Prezzo unitario', digits=(16, 2))
    line_total = fields.Float(string='Totale riga', digits=(16, 2))
    tax_rate_foreign = fields.Float(
        string='Aliquota IVA estera (%)',
        digits=(5, 2),
        help='Aliquota IVA estera applicata dal fornitore (informativo)',
    )
