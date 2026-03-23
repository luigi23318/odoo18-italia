import base64
import json
import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ArubaSdiService(models.AbstractModel):
    _name = 'aruba.sdi.service'
    _description = 'Servizio Integrazione Aruba Fatturazione Elettronica Premium'

    # -------------------------------------------------------------------------
    # CONFIGURAZIONE
    # -------------------------------------------------------------------------

    def _get_config(self):
        """Recupera configurazione Aruba da parametri di sistema."""
        ICP = self.env['ir.config_parameter'].sudo()
        env_mode = ICP.get_param(
            'l10n_it_foreign_invoice_sdi.aruba_environment', 'sandbox'
        )
        if env_mode == 'production':
            base_url = 'https://ws.fatturazioneelettronica.aruba.it'
        else:
            base_url = 'https://demows.fatturazioneelettronica.aruba.it'

        return {
            'base_url': base_url,
            'username': ICP.get_param('l10n_it_foreign_invoice_sdi.aruba_username', ''),
            'password': ICP.get_param('l10n_it_foreign_invoice_sdi.aruba_password', ''),
            'environment': env_mode,
        }

    def _get_auth_token(self, config):
        """Ottieni token di autenticazione Aruba."""
        url = f"{config['base_url']}/services/authentication/login"
        payload = {
            'username': config['username'],
            'password': config['password'],
        }
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get('token') or data.get('access_token')
        except requests.RequestException as e:
            raise UserError(
                _('Errore autenticazione Aruba: %s') % str(e)
            ) from e

    # -------------------------------------------------------------------------
    # INVIO FATTURA
    # -------------------------------------------------------------------------

    def send_invoice(self, invoice):
        """Invia una fattura XML al SDI tramite Aruba.

        :param invoice: record foreign.invoice.import
        :returns: dict con file_id e altre info
        """
        if not invoice.xml_file:
            raise UserError(_('Nessun file XML da inviare.'))

        config = self._get_config()
        if not config['username'] or not config['password']:
            raise UserError(
                _('Configurare le credenziali Aruba nelle impostazioni del modulo.')
            )

        token = self._get_auth_token(config)
        url = f"{config['base_url']}/services/invoice/upload"

        xml_data = base64.b64decode(invoice.xml_file)
        payload = {
            'dataFile': base64.b64encode(xml_data).decode('utf-8'),
            'credential': token,
            'domain': 'fatturapa',
        }

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

            if result.get('errorCode'):
                raise UserError(
                    _('Errore invio Aruba: [%s] %s') % (
                        result.get('errorCode'),
                        result.get('errorDescription', ''),
                    )
                )

            _logger.info(
                'Fattura %s inviata con successo. File ID: %s',
                invoice.name,
                result.get('uploadFileName'),
            )
            return {
                'file_id': result.get('uploadFileName', ''),
                'raw_response': json.dumps(result),
            }

        except requests.RequestException as e:
            raise UserError(
                _('Errore comunicazione Aruba: %s') % str(e)
            ) from e

    # -------------------------------------------------------------------------
    # CONTROLLO NOTIFICHE
    # -------------------------------------------------------------------------

    def check_notification(self, invoice):
        """Controlla notifiche SDI per una fattura.

        :param invoice: record foreign.invoice.import
        """
        if not invoice.sdi_file_id:
            return

        config = self._get_config()
        token = self._get_auth_token(config)
        url = f"{config['base_url']}/services/notification/out/getByInvoiceFilename"

        payload = {
            'credential': token,
            'invoiceFilename': invoice.sdi_file_id,
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

            notifications = result.get('notifications', [])
            for notif in notifications:
                notif_type = notif.get('type', '')
                existing = invoice.sdi_notification_ids.filtered(
                    lambda n: n.sdi_message_id == notif.get('messageId')
                )
                if existing:
                    continue

                self.env['foreign.invoice.sdi.notification'].create({
                    'import_id': invoice.id,
                    'notification_type': notif_type,
                    'notification_date': notif.get('date', fields.Datetime.now()),
                    'sdi_message_id': notif.get('messageId'),
                    'raw_content': json.dumps(notif),
                })

                # Aggiorna stato fattura in base alla notifica
                self._update_invoice_state(invoice, notif_type)

        except requests.RequestException as e:
            _logger.warning('Errore check notifiche Aruba: %s', e)

    def _update_invoice_state(self, invoice, notification_type):
        """Aggiorna stato fattura in base al tipo di notifica ricevuta."""
        state_map = {
            'RC': 'delivered',    # Ricevuta di Consegna
            'NS': 'rejected',    # Notifica di Scarto
            'MC': 'sent',        # Mancata Consegna (resta inviata)
            'NE': 'accepted',    # Notifica Esito (accettata)
            'DT': 'accepted',    # Decorrenza Termini (silenzio-assenso)
            'AT': 'delivered',   # Attestazione trasmissione
        }
        new_state = state_map.get(notification_type)
        if new_state:
            vals = {'state': new_state}
            if new_state == 'delivered':
                vals['sdi_delivery_date'] = fields.Datetime.now()
            invoice.write(vals)

    # -------------------------------------------------------------------------
    # POLLING CRON
    # -------------------------------------------------------------------------

    @api.model
    def cron_check_sdi_notifications(self):
        """Cron job: controlla notifiche SDI per tutte le fatture in attesa."""
        invoices = self.env['foreign.invoice.import'].search([
            ('state', '=', 'sent'),
            ('sdi_file_id', '!=', False),
        ])
        _logger.info('Polling SDI: %d fatture da controllare', len(invoices))
        for invoice in invoices:
            try:
                self.check_notification(invoice)
            except Exception as e:
                _logger.error('Errore polling SDI per %s: %s', invoice.name, e)
        return True
