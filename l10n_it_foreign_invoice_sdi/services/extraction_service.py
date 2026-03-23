import logging

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ExtractionService(models.AbstractModel):
    _name = 'foreign.invoice.extraction.service'
    _description = 'Servizio Orchestratore Estrazione Dati Fattura'

    @api.model
    def extract(self, invoice, engine='tesseract'):
        """Esegue l'estrazione dati dal PDF della fattura.

        :param invoice: record foreign.invoice.import
        :param engine: 'tesseract' o 'acube'
        """
        if not invoice.pdf_file:
            raise UserError(_('Nessun PDF caricato sulla fattura %s.') % invoice.name)

        if engine == 'tesseract':
            data = self.env['foreign.invoice.ocr.service'].extract_from_pdf(
                invoice.pdf_file
            )
        elif engine == 'acube':
            data = self.env['foreign.invoice.acube.extraction.service'].extract_from_pdf(
                invoice.pdf_file
            )
        else:
            raise UserError(_('Motore di estrazione "%s" non supportato.') % engine)

        if not data:
            _logger.warning('Nessun dato estratto per %s', invoice.name)
            return

        # Aggiorna campi fattura con dati estratti
        vals = {}
        if data.get('invoice_number'):
            vals['invoice_number'] = data['invoice_number']
        if data.get('invoice_date'):
            vals['invoice_date'] = data['invoice_date']
        if data.get('supplier_vat'):
            vals['supplier_vat'] = data['supplier_vat']
            # Tenta di trovare il partner e il paese dalla P.IVA
            country_code = data['supplier_vat'][:2]
            country = self.env['res.country'].search(
                [('code', '=', country_code)], limit=1
            )
            if country:
                vals['supplier_country_id'] = country.id
            partner = self.env['res.partner'].search(
                [('vat', '=', data['supplier_vat'])], limit=1
            )
            if partner:
                vals['supplier_partner_id'] = partner.id
                vals['supplier_denomination'] = partner.name
        if data.get('supplier_denomination') and 'supplier_denomination' not in vals:
            vals['supplier_denomination'] = data['supplier_denomination']
        if data.get('confidence'):
            vals['extraction_confidence'] = data['confidence']

        # Righe fattura (se presenti)
        if data.get('lines'):
            line_vals = []
            for line_data in data['lines']:
                line_vals.append((0, 0, {
                    'description': line_data.get('description', '/'),
                    'quantity': line_data.get('quantity', 1),
                    'unit_price': line_data.get('unit_price', 0),
                    'tax_rate': line_data.get('tax_rate', 0),
                }))
            vals['line_ids'] = line_vals

        if vals:
            invoice.write(vals)
            _logger.info(
                'Estrazione completata per %s (engine=%s, confidence=%.1f%%)',
                invoice.name, engine, data.get('confidence', 0),
            )
