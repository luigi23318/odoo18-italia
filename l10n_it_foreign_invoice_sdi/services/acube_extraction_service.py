import base64
import logging
import time
from typing import Optional

import requests

_logger = logging.getLogger(__name__)


class AcubeExtractionService:
    """Client A-Cube API per estrazione dati da PDF fattura.

    A-Cube e' usato SOLO per estrazione, NON per invio SDI.
    """

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1  # secondi

    def __init__(self, env) -> None:
        ICP = env['ir.config_parameter'].sudo()
        self.email = ICP.get_param('foreign_invoice.acube_email', '')
        self.password = ICP.get_param('foreign_invoice.acube_password', '')
        self.environment = ICP.get_param(
            'foreign_invoice.acube_environment', 'sandbox',
        )
        if self.environment == 'sandbox':
            self.base_url = 'https://api-sandbox.acubeapi.com'
            self.common_url = 'https://common-sandbox.api.acubeapi.com'
        else:
            self.base_url = 'https://api.acubeapi.com'
            self.common_url = 'https://common.api.acubeapi.com'
        self.token: Optional[str] = None

    def _authenticate(self) -> None:
        """Login A-Cube, ottiene token JWT."""
        if not self.email or not self.password:
            raise ValueError(
                'Credenziali A-Cube non configurate. '
                'Impostare email e password in Impostazioni > Contabilità.'
            )
        _logger.info('Autenticazione A-Cube (%s)', self.environment)
        resp = requests.post(
            f'{self.common_url}/login',
            json={'email': self.email, 'password': self.password},
            timeout=30,
        )
        resp.raise_for_status()
        self.token = resp.json().get('token')
        if not self.token:
            raise ValueError('Token A-Cube non ricevuto.')
        _logger.info('Autenticazione A-Cube riuscita.')

    def extract_invoice(self, attachment: 'ir.attachment') -> Optional[dict]:
        """Invia PDF ad A-Cube, riceve JSON strutturato.

        Retry con backoff esponenziale per errori 5xx.
        Nessun retry per 4xx.
        """
        if not self.token:
            self._authenticate()

        pdf_content = base64.b64decode(attachment.datas)
        _logger.info('Invio PDF a A-Cube per estrazione: %s', attachment.name)

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = requests.post(
                    f'{self.base_url}/invoices/extract',
                    headers={'Authorization': f'Bearer {self.token}'},
                    files={
                        'file': (
                            attachment.name, pdf_content, 'application/pdf',
                        )
                    },
                    timeout=60,
                )

                if resp.status_code == 401:
                    _logger.info('Token scaduto, re-autenticazione.')
                    self._authenticate()
                    continue

                if resp.status_code >= 500:
                    backoff = self.INITIAL_BACKOFF * (2 ** attempt)
                    _logger.warning(
                        'A-Cube errore %d, retry in %ds (tentativo %d/%d)',
                        resp.status_code, backoff,
                        attempt + 1, self.MAX_RETRIES,
                    )
                    time.sleep(backoff)
                    continue

                resp.raise_for_status()
                data = resp.json()
                return self._map_to_odoo(data)

            except requests.exceptions.Timeout:
                _logger.warning(
                    'Timeout A-Cube, tentativo %d/%d',
                    attempt + 1, self.MAX_RETRIES,
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.INITIAL_BACKOFF * (2 ** attempt))
                    continue
                raise

        raise ValueError(
            f'A-Cube: estrazione fallita dopo {self.MAX_RETRIES} tentativi.'
        )

    def _map_to_odoo(self, data: dict) -> dict:
        """Converte formato JSON A-Cube in formato Odoo."""
        supplier = data.get('supplier', {})
        result = {
            'invoice_number': data.get('invoice_number'),
            'invoice_date': data.get('date'),
            'supplier_name': supplier.get('name'),
            'supplier_vat': supplier.get('vat_number'),
            'country_code': supplier.get('country'),
            'currency_code': data.get('currency'),
            'amount_untaxed': data.get('total_net'),
            'amount_tax': data.get('total_tax'),
            'amount_total': data.get('total_amount'),
            'line_items': [
                {
                    'description': li.get('description'),
                    'quantity': li.get('quantity', 1),
                    'unit_price': li.get('unit_price', 0),
                    'total': li.get('total', 0),
                }
                for li in data.get('line_items', [])
            ],
        }
        _logger.info(
            'Mapping A-Cube completato: fornitore=%s, totale=%s',
            result.get('supplier_name'), result.get('amount_total'),
        )
        return result
