from odoo import api, fields, models


class ForeignInvoiceImportLine(models.Model):
    _name = 'foreign.invoice.import.line'
    _description = 'Riga Fattura Estera'
    _order = 'sequence, id'

    import_id = fields.Many2one(
        'foreign.invoice.import',
        string='Fattura',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(
        string='Sequenza',
        default=10,
    )
    description = fields.Char(
        string='Descrizione',
        required=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Prodotto',
    )
    quantity = fields.Float(
        string='Quantità',
        default=1.0,
    )
    uom = fields.Char(
        string='Unità di Misura',
    )
    unit_price = fields.Float(
        string='Prezzo Unitario',
        digits='Product Price',
    )
    discount = fields.Float(
        string='Sconto (%)',
        digits='Discount',
    )
    price_subtotal = fields.Monetary(
        string='Imponibile',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    tax_rate = fields.Float(
        string='Aliquota IVA (%)',
    )
    tax_ids = fields.Many2many(
        'account.tax',
        string='Imposte',
    )
    tax_amount = fields.Monetary(
        string='Importo Imposta',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    currency_id = fields.Many2one(
        related='import_id.currency_id',
        store=True,
    )

    # Natura (per operazioni non imponibili/esenti/escluse)
    natura = fields.Selection(
        selection=[
            ('N1', 'N1 - Escluse ex art.15'),
            ('N2', 'N2 - Non soggette'),
            ('N2.1', 'N2.1 - Non soggette artt. da 7 a 7-septies'),
            ('N2.2', 'N2.2 - Non soggette - altri casi'),
            ('N3', 'N3 - Non imponibili'),
            ('N3.1', 'N3.1 - Non imponibili - esportazioni'),
            ('N3.2', 'N3.2 - Non imponibili - cessioni intraUE'),
            ('N3.3', 'N3.3 - Non imponibili - cessioni San Marino'),
            ('N3.4', 'N3.4 - Non imponibili - op. assimilate cessioni export'),
            ('N3.5', 'N3.5 - Non imponibili - a seguito dichiarazioni intento'),
            ('N3.6', 'N3.6 - Non imponibili - altre operazioni'),
            ('N4', 'N4 - Esenti'),
            ('N5', 'N5 - Regime del margine / IVA non esposta'),
            ('N6', 'N6 - Inversione contabile (reverse charge)'),
            ('N6.1', 'N6.1 - RC - cessione rottami'),
            ('N6.2', 'N6.2 - RC - cessione oro/argento'),
            ('N6.3', 'N6.3 - RC - subappalto edilizia'),
            ('N6.4', 'N6.4 - RC - cessione fabbricati'),
            ('N6.5', 'N6.5 - RC - cessione telefoni cellulari'),
            ('N6.6', 'N6.6 - RC - cessione prodotti elettronici'),
            ('N6.7', 'N6.7 - RC - prestazioni settore edile'),
            ('N6.8', 'N6.8 - RC - operazioni settore energetico'),
            ('N6.9', 'N6.9 - RC - altri casi'),
            ('N7', 'N7 - IVA assolta in altro stato UE'),
        ],
        string='Natura',
    )

    @api.depends('quantity', 'unit_price', 'discount', 'tax_rate')
    def _compute_amounts(self):
        for line in self:
            subtotal = line.quantity * line.unit_price
            if line.discount:
                subtotal *= (1 - line.discount / 100.0)
            line.price_subtotal = subtotal
            line.tax_amount = subtotal * (line.tax_rate / 100.0)
