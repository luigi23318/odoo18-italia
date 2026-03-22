import logging
import os
import re
from typing import Optional

import yaml

_logger = logging.getLogger(__name__)


class ExtractionService:
    """Wrapper invoice2data: carica template YAML e estrae campi strutturati."""

    def __init__(self) -> None:
        self.templates_dir = os.path.join(
            os.path.dirname(__file__), '..', 'data', 'templates',
        )
        self.templates = self._load_templates()

    def _load_templates(self) -> list[dict]:
        """Carica tutti i template YAML dalla directory."""
        templates = []
        if not os.path.isdir(self.templates_dir):
            _logger.warning(
                'Directory template non trovata: %s', self.templates_dir,
            )
            return templates

        for filename in sorted(os.listdir(self.templates_dir)):
            if filename.endswith(('.yml', '.yaml')):
                filepath = os.path.join(self.templates_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        template = yaml.safe_load(f)
                    if template:
                        template['_filename'] = filename
                        templates.append(template)
                except Exception:
                    _logger.exception(
                        'Errore caricamento template %s', filename,
                    )
        _logger.info('Caricati %d template YAML', len(templates))
        return templates

    def extract_fields(self, raw_text: str) -> Optional[dict]:
        """Cerca un template corrispondente e estrae i campi.

        Returns dict con campi estratti, o None se nessun match.
        """
        if not raw_text or not self.templates:
            return None

        for template in self.templates:
            if self._matches_template(raw_text, template):
                _logger.info(
                    'Template match: %s (%s)',
                    template.get('issuer', '?'),
                    template.get('_filename', '?'),
                )
                return self._extract_from_template(raw_text, template)

        _logger.info('Nessun template corrisponde al testo.')
        return None

    def _matches_template(self, text: str, template: dict) -> bool:
        """Verifica se tutte le keyword del template sono presenti nel testo."""
        keywords = template.get('keywords', [])
        if not keywords:
            return False
        text_lower = text.lower()
        return all(kw.lower() in text_lower for kw in keywords)

    def _extract_from_template(self, text: str, template: dict) -> dict:
        """Estrae i campi dal testo usando le regex del template."""
        result = {}

        # Campi statici
        static = template.get('static_fields', {})
        if static.get('supplier_vat'):
            result['supplier_vat'] = static['supplier_vat']
        if static.get('supplier_country'):
            result['country_code'] = static['supplier_country']
        if static.get('tipo_documento'):
            result['tipo_documento'] = static['tipo_documento']
        if static.get('description_type'):
            result['description_type'] = static['description_type']

        result['supplier_name'] = template.get('issuer', '')

        # Campi regex
        field_patterns = template.get('fields', {})
        options = template.get('options', {})
        date_formats = options.get('date_formats', ['%d/%m/%Y'])
        decimal_sep = options.get('decimal_separator', ',')
        currency = options.get('currency', 'EUR')

        result['currency_code'] = currency

        for field_name, pattern in field_patterns.items():
            match = re.search(pattern, text)
            if match:
                value = match.group(1)
                if field_name == 'invoice_number':
                    result['invoice_number'] = value.strip()
                elif field_name == 'date':
                    result['invoice_date'] = self._parse_date(
                        value.strip(), date_formats,
                    )
                elif field_name in (
                    'amount_total', 'amount_untaxed', 'vat_amount',
                ):
                    parsed = self._parse_amount(value.strip(), decimal_sep)
                    if field_name == 'amount_total':
                        result['amount_total'] = parsed
                    elif field_name == 'amount_untaxed':
                        result['amount_untaxed'] = parsed
                    elif field_name == 'vat_amount':
                        result['amount_tax'] = parsed

        return result

    def _parse_date(self, value: str, formats: list[str]) -> Optional[str]:
        """Parse data con formati multipli."""
        from datetime import datetime
        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        _logger.warning('Impossibile parsare data: %s', value)
        return None

    def _parse_amount(self, value: str, decimal_sep: str = ',') -> float:
        """Parse importo con separatore decimale configurabile."""
        try:
            cleaned = value.replace(' ', '')
            if decimal_sep == ',':
                cleaned = cleaned.replace('.', '').replace(',', '.')
            elif decimal_sep == '.':
                cleaned = cleaned.replace(',', '')
            return float(cleaned)
        except (ValueError, TypeError):
            _logger.warning('Impossibile parsare importo: %s', value)
            return 0.0
