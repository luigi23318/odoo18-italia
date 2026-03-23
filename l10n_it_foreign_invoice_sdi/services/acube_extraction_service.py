import base64
import logging

import requests

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcubeExtractionService(models.AbstractModel):
    _name = 'foreign.invoice.acube.extraction.service'
    _description = 'Servizio Estrazione A-Cube Cloud API'

    @api.model
    def _get_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'api_url': ICP.get_param(
                'l10n_it_foreign_invoice_sdi.acube_api_url',
                'https://api.acube.cloud',
            ),
            'api_key': ICP.get_param(
                'l10n_it_foreign_invoice_sdi.acube_api_key', ''
            ),
        }

    @api.model
    def extract_from_pdf(self, pdf_binary):
        """Estrae dati fattura tramite A-Cube API.

        :param pdf_binary: base64-encoded PDF content
        :returns: dict con dati estratti
        """
        config = self._get_config()
        if not config['api_key']:
            raise UserError(
                _('API Key A-Cube non configurata. '
                  'Vai in Impostazioni > Fatture Estere SDI.')
            )

        url = f"{config['api_url']}/v1/invoices/extract"
        headers = {
            'Authorization': f"Bearer {config['api_key']}",
            'Content-Type': 'application/json',
        }
        payload = {
            'document': pdf_binary.decode('utf-8') if isinstance(pdf_binary, bytes) else pdf_binary,
            'document_type': 'invoice',
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            return self._map_response(data)
        except requests.RequestException as e:
            _logger.error('Errore A-Cube API: %s', e)
            raise UserError(
                _('Errore comunicazione A-Cube: %s') % str(e)
            ) from e

    @api.model
    def _map_response(self, data):
        """Mappa la risposta A-Cube al formato interno.

        :param data: dict risposta API
        :returns: dict normalizzato
        """
        result = {
            'confidence': data.get('confidence', 0) * 100,
        }

        # Dati fornitore
        supplier = data.get('supplier', {})
        if supplier.get('name'):
            result['supplier_denomination'] = supplier['name']
        if supplier.get('vat_number'):
            result['supplier_vat'] = supplier['vat_number']

        # Dati fattura
        if data.get('invoice_number'):
            result['invoice_number'] = data['invoice_number']
        if data.get('invoice_date'):
            result['invoice_date'] = data['invoice_date']
        if data.get('total_amount'):
            result['total_amount'] = data['total_amount']

        # Righe
        lines = []
        for item in data.get('line_items', []):
            lines.append({
                'description': item.get('description', '/'),
                'quantity': item.get('quantity', 1),
                'unit_price': item.get('unit_price', 0),
                'tax_rate': item.get('tax_rate', 0),
            })
        if lines:
            result['lines'] = lines

        return result
