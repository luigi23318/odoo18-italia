import base64
import logging
import time

import requests

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ArubaSdiService(models.AbstractModel):
    _name = 'aruba.sdi.service'
    _description = 'Client Aruba Fatturazione Elettronica Premium API'

    DEMO_BASE_URL = 'https://demows.fatturazioneelettronica.aruba.it'
    PROD_BASE_URL = 'https://ws.fatturazioneelettronica.aruba.it'

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1

    @api.model
    def _get_config(self) -> dict:
        """Legge le credenziali da ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        environment = ICP.get_param(
            'foreign_invoice.aruba_environment', 'demo',
        )
        return {
            'username': ICP.get_param('foreign_invoice.aruba_username', ''),
            'password': ICP.get_param('foreign_invoice.aruba_password', ''),
            'environment': environment,
            'base_url': (
                self.PROD_BASE_URL
                if environment == 'production'
                else self.DEMO_BASE_URL
            ),
            'sdi_active': ICP.get_param(
                'foreign_invoice.sdi_active', 'False',
            ) in ('True', 'true', '1', True),
        }

    @api.model
    def _authenticate(self, config: dict) -> str:
        """Autenticazione Aruba Premium API — POST /auth/signin."""
        if not config['username'] or not config['password']:
            raise UserError(
                _('Credenziali Aruba Premium non configurate. '
                  'Impostare in Impostazioni > Contabilità.')
            )
        _logger.info(
            'Autenticazione Aruba Premium (%s)', config['environment'],
        )
        resp = requests.post(
            f"{config['base_url']}/auth/signin",
            json={
                'username': config['username'],
                'password': config['password'],
            },
            timeout=30,
        )
        resp.raise_for_status()
        token = resp.json().get('access_token') or resp.json().get('token')
        if not token:
            raise UserError(_('Token Aruba non ricevuto.'))
        _logger.info('Autenticazione Aruba riuscita.')
        return token

    @api.model
    def send_invoice(self, invoice: 'foreign.invoice.import') -> None:
        """Invia XML FatturaPA allo SDI — POST /services/invoice/upload."""
        config = self._get_config()
        if not config['sdi_active']:
            raise UserError(
                _('Invio SDI non attivo. '
                  'Attivare in Impostazioni > Contabilità, oppure '
                  "usare 'Scarica XML' per upload manuale.")
            )

        if not invoice.xml_attachment_id:
            raise UserError(_('Nessun XML generato per questa fattura.'))

        token = self._authenticate(config)
        xml_data = base64.b64decode(invoice.xml_attachment_id.datas)
        filename = invoice.xml_filename or invoice.xml_attachment_id.name

        _logger.info(
            'Invio XML allo SDI: %s (%s)', filename, invoice.name,
        )

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = requests.post(
                    f"{config['base_url']}/services/invoice/upload",
                    headers={'Authorization': f'Bearer {token}'},
                    json={
                        'dataFile': base64.b64encode(xml_data).decode('utf-8'),
                        'credential': '',
                        'domain': '',
                    },
                    timeout=30,
                )

                if resp.status_code >= 500:
                    backoff = self.INITIAL_BACKOFF * (2 ** attempt)
                    _logger.warning(
                        'Aruba errore %d, retry in %ds (%d/%d)',
                        resp.status_code, backoff,
                        attempt + 1, self.MAX_RETRIES,
                    )
                    time.sleep(backoff)
                    continue

                resp.raise_for_status()
                result = resp.json()

                invoice.write({
                    'sdi_id': result.get('uploadFileName', ''),
                    'sdi_filename': filename,
                    'sdi_state': 'sent',
                    'state': 'inviato_sdi',
                })
                _logger.info(
                    'XML inviato allo SDI: %s, uploadFileName=%s',
                    invoice.name, result.get('uploadFileName'),
                )
                return

            except requests.exceptions.Timeout:
                _logger.warning(
                    'Timeout invio SDI, tentativo %d/%d',
                    attempt + 1, self.MAX_RETRIES,
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.INITIAL_BACKOFF * (2 ** attempt))
                    continue
                raise UserError(
                    _('Timeout invio SDI dopo %d tentativi.')
                    % self.MAX_RETRIES
                )

        raise UserError(
            _('Invio SDI fallito dopo %d tentativi.') % self.MAX_RETRIES
        )

    @api.model
    def check_notification(self, invoice: 'foreign.invoice.import') -> None:
        """Verifica notifiche SDI — GET /services/notification/out/getByFilename."""
        if not invoice.sdi_filename:
            return

        config = self._get_config()
        if not config['sdi_active']:
            return

        token = self._authenticate(config)

        try:
            resp = requests.get(
                f"{config['base_url']}/services/notification/out/getByFilename",
                headers={'Authorization': f'Bearer {token}'},
                params={'filename': invoice.sdi_filename},
                timeout=30,
            )
            resp.raise_for_status()
            notifications = resp.json()

            if not notifications:
                return

            for notif in (
                notifications if isinstance(notifications, list)
                else [notifications]
            ):
                notif_type = notif.get('type', '').lower()
                if notif_type in ('rc', 'ricevutaconsegna'):
                    invoice.write({
                        'sdi_state': 'delivered',
                        'state': 'consegnato',
                    })
                    _logger.info(
                        'Fattura %s consegnata dallo SDI', invoice.name,
                    )
                elif notif_type in ('ns', 'notificascarto'):
                    invoice.write({
                        'sdi_state': 'rejected',
                        'state': 'scartato',
                        'validation_errors': notif.get('description', ''),
                    })
                    _logger.warning(
                        'Fattura %s scartata dallo SDI: %s',
                        invoice.name, notif.get('description'),
                    )
        except Exception:
            _logger.exception(
                'Errore polling notifiche SDI per %s', invoice.name,
            )

    @api.model
    def cron_poll_sdi_notifications(self) -> None:
        """Cron job: polling notifiche per tutte le fatture inviate."""
        _logger.info('Inizio polling notifiche SDI')
        invoices = self.env['foreign.invoice.import'].search([
            ('state', '=', 'inviato_sdi'),
            ('sdi_filename', '!=', False),
        ])

        for inv in invoices:
            try:
                self.check_notification(inv)
            except Exception:
                _logger.exception(
                    'Errore polling notifica per %s', inv.name,
                )

        _logger.info(
            'Polling notifiche SDI completato: %d fatture verificate',
            len(invoices),
        )

    @api.model
    def get_multicedenti(self) -> list:
        """Lista cedenti — GET /auth/multicedenti."""
        config = self._get_config()
        token = self._authenticate(config)
        resp = requests.get(
            f"{config['base_url']}/auth/multicedenti",
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @api.model
    def switch_account(self, vat: str) -> None:
        """Switch contesto P.IVA — POST /auth/switchAccount."""
        config = self._get_config()
        token = self._authenticate(config)
        resp = requests.post(
            f"{config['base_url']}/auth/switchAccount",
            headers={'Authorization': f'Bearer {token}'},
            json={'vat': vat},
            timeout=30,
        )
        resp.raise_for_status()
        _logger.info('Switch account Aruba a P.IVA: %s', vat)
