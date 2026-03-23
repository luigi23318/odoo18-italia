import base64
import io
import logging
import re

from odoo import api, models

_logger = logging.getLogger(__name__)

try:
    import pdfplumber
except ImportError:
    pdfplumber = None
    _logger.warning('pdfplumber non installato. Estrazione PDF non disponibile.')


class OcrService(models.AbstractModel):
    _name = 'foreign.invoice.ocr.service'
    _description = 'Servizio OCR Tesseract per Fatture Estere'

    @api.model
    def extract_from_pdf(self, pdf_binary):
        """Estrae testo da un file PDF usando pdfplumber.

        :param pdf_binary: base64-encoded PDF content
        :returns: dict con dati estratti
        """
        if not pdfplumber:
            _logger.error('pdfplumber non disponibile')
            return {}

        pdf_data = base64.b64decode(pdf_binary)
        text = ''

        with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'

        if not text.strip():
            _logger.warning('Nessun testo estratto dal PDF')
            return {}

        return self._parse_text(text)

    @api.model
    def _parse_text(self, text):
        """Parsing del testo estratto per individuare campi fattura.

        :param text: testo grezzo
        :returns: dict con campi estratti
        """
        result = {
            'raw_text': text,
            'confidence': 0.0,
        }
        fields_found = 0
        total_fields = 5  # campi principali cercati

        # Invoice number
        inv_match = re.search(
            r'(?:invoice|fattura|rechnung|facture)\s*(?:n[.ºr°]?|number|nr)?\s*[:\s]?\s*([A-Z0-9][\w\-/]+)',
            text, re.IGNORECASE,
        )
        if inv_match:
            result['invoice_number'] = inv_match.group(1).strip()
            fields_found += 1

        # Date
        date_match = re.search(
            r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})',
            text,
        )
        if date_match:
            day, month, year = date_match.groups()
            if len(year) == 2:
                year = '20' + year
            result['invoice_date'] = f'{year}-{month.zfill(2)}-{day.zfill(2)}'
            fields_found += 1

        # VAT number
        vat_match = re.search(
            r'(?:vat|tva|ust|mwst|iva)\s*(?:id|nr|n[.°]?)?\s*[:\s]?\s*([A-Z]{2}\s*\d[\d\s]{5,})',
            text, re.IGNORECASE,
        )
        if vat_match:
            result['supplier_vat'] = re.sub(r'\s', '', vat_match.group(1))
            fields_found += 1

        # Total amount
        total_match = re.search(
            r'(?:total|totale|gesamt|montant)\s*[:\s]?\s*[€$£]?\s*([\d.,]+)',
            text, re.IGNORECASE,
        )
        if total_match:
            amount_str = total_match.group(1).replace('.', '').replace(',', '.')
            try:
                result['total_amount'] = float(amount_str)
                fields_found += 1
            except ValueError:
                pass

        # Company name (first line heuristic)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if lines:
            result['supplier_denomination'] = lines[0][:100]
            fields_found += 1

        result['confidence'] = (fields_found / total_fields) * 100
        return result
