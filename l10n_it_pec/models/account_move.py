# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import logging
import re
import smtplib
from email.message import EmailMessage

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Mapping notifiche SDI → stato l10n_it_edi nativo Odoo 18
# RC  = Ricevuta di Consegna         → delivered (accettata)
# NS  = Notifica di Scarto           → invalid (XML non valido)
# MC  = Mancata Consegna             → awaiting (in attesa retry)
# AT  = Attestazione                  → delivered
# NE  = Notifica Esito (accettata)   → delivered
# NE  = Notifica Esito (rifiutata)   → invalid
# DT  = Decorrenza Termini           → delivered (silenzio-assenso)
SDI_NOTIFICATION_MAP = {
    'RC': 'delivered',
    'NS': 'invalid',
    'MC': 'awaiting',
    'AT': 'delivered',
    'DT': 'delivered',
    # NE dipende dal contenuto (Accettazione/Rifiuto)
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ── Campi PEC (informativi, NON duplicano lo stato EDI) ───────────
    l10n_it_pec_sent_date = fields.Datetime(
        string='Data invio PEC',
        readonly=True,
        copy=False,
    )
    l10n_it_pec_message_id = fields.Char(
        string='Message-ID PEC',
        readonly=True,
        copy=False,
        help="Message-ID dell'email PEC inviata, per correlazione notifiche.",
    )
    l10n_it_pec_xml_attachment_id = fields.Many2one(
        'ir.attachment',
        string='XML FatturaPA (PEC)',
        readonly=True,
        copy=False,
    )
    l10n_it_pec_last_error = fields.Text(
        string='Ultimo errore PEC',
        readonly=True,
        copy=False,
    )

    # ══════════════════════════════════════════════════════════════════
    #  CUORE OPZIONE C: Intercettazione del trasporto EDI
    # ══════════════════════════════════════════════════════════════════

    def _l10n_it_edi_pec_is_active(self):
        """Verifica se la modalità PEC è attiva per questa fattura."""
        self.ensure_one()
        return self.company_id.l10n_it_edi_pec_mode in ('demo', 'test', 'production')

    def _l10n_it_edi_send(self, attachments_vals):
        """
        Override CHIAVE — Opzione C.

        Odoo 18 chiama questo metodo per inviare la fattura allo SDI.
        Se la modalità PEC è attiva, intercettiamo e usiamo il trasporto PEC.
        Altrimenti, passiamo al flusso standard (proxy Odoo).

        L'XML viene generato dal motore standard _l10n_it_edi_export_invoice_as_xml(),
        noi cambiamo SOLO il trasporto.
        """
        pec_moves = self.filtered(lambda m: m._l10n_it_edi_pec_is_active())
        standard_moves = self - pec_moves

        results = {}

        # Fatture che usano il canale standard
        if standard_moves:
            standard_attachments = {m: v for m, v in attachments_vals.items() if m in standard_moves}
            results.update(super(AccountMove, standard_moves)._l10n_it_edi_send(standard_attachments))

        # Fatture che usano il canale PEC
        for move in pec_moves:
            attachment = attachments_vals.get(move, {})
            filename = attachment.get('name', '')
            try:
                move._l10n_it_pec_send_to_sdi()
                results[filename] = {}
            except Exception as e:
                _logger.exception(
                    "Errore invio PEC fattura %s: %s", move.name, str(e)
                )
                move.l10n_it_pec_last_error = str(e)
                move.message_post(
                    body=_("❌ Errore invio PEC allo SDI: %s") % str(e),
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                )
                results[filename] = {'error_message': str(e)}

        return results

    # ══════════════════════════════════════════════════════════════════
    #  Generazione XML e invio PEC
    # ══════════════════════════════════════════════════════════════════

    def _l10n_it_pec_generate_xml(self):
        """
        Genera l'XML FatturaPA riutilizzando il motore standard di l10n_it_edi.
        Salva l'XML come allegato sulla fattura.

        Compatibilità: prova diversi nomi di metodo usati nelle varie
        versioni di Odoo 18 CE per la generazione XML FatturaPA.
        """
        self.ensure_one()

        xml_content = None
        errors = []

        # Strategia 1: metodo diretto Odoo 18 (più recente)
        if hasattr(self, '_l10n_it_edi_export_invoice_as_xml'):
            try:
                result = self._l10n_it_edi_export_invoice_as_xml()
                if isinstance(result, tuple):
                    xml_content, errors = result
                else:
                    xml_content = result
            except Exception as e:
                _logger.warning(
                    "_l10n_it_edi_export_invoice_as_xml fallito: %s", e
                )

        # Strategia 2: via l10n_it_edi_content field (computed)
        if not xml_content and hasattr(self, 'l10n_it_edi_content'):
            try:
                content = self.l10n_it_edi_content
                if content:
                    xml_content = base64.b64decode(content) if isinstance(content, str) else content
            except Exception as e:
                _logger.warning(
                    "l10n_it_edi_content fallito: %s", e
                )

        # Strategia 3: via account.edi.xml.cii (se disponibile)
        if not xml_content:
            try:
                builder = self.env.get('account.edi.xml.it_fatturapa')
                if builder:
                    xml_content = builder._export_invoice(self)
            except Exception as e:
                _logger.warning(
                    "account.edi.xml.it_fatturapa fallito: %s", e
                )

        # Strategia 4: via il vecchio account.edi.format
        if not xml_content:
            try:
                edi_format = self.env.ref('l10n_it_edi.edi_format_it', raise_if_not_found=False)
                if edi_format:
                    result = edi_format._export_invoice(self)
                    if isinstance(result, tuple):
                        xml_content = result[0]
                    else:
                        xml_content = result
            except Exception as e:
                _logger.warning(
                    "account.edi.format._export_invoice fallito: %s", e
                )

        if not xml_content:
            raise UserError(
                _("Impossibile generare l'XML FatturaPA. "
                  "Nessun metodo di esportazione disponibile.\n"
                  "Verificare che il modulo l10n_it_edi sia installato "
                  "e la fattura sia correttamente configurata.")
            )

        if errors:
            raise UserError(
                _("Errori nella generazione XML FatturaPA:\n%s")
                % '\n'.join(str(e) for e in errors)
            )

        # Nome file secondo specifiche SDI:
        # IT + PartitaIVA + _ + progressivo univoco
        vat = (self.company_id.vat or '').replace(' ', '')
        if vat.startswith('IT'):
            vat = vat[2:]
        filename = f"IT{vat}_{self.name.replace('/', '_')}.xml"

        # Salva come allegato
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'raw': xml_content if isinstance(xml_content, bytes) else xml_content.encode('utf-8'),
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/xml',
        })
        self.l10n_it_pec_xml_attachment_id = attachment

        return xml_content, filename

    def _l10n_it_pec_send_to_sdi(self):
        """
        Invia la fattura allo SDI via PEC.
        In modalità demo, logga senza inviare.
        """
        self.ensure_one()
        company = self.company_id

        # Genera XML
        xml_content, filename = self._l10n_it_pec_generate_xml()

        mode = company.l10n_it_edi_pec_mode

        # ── DEMO MODE: dry-run ────────────────────────────────────────
        if mode == 'demo':
            _logger.info(
                "[PEC DEMO] Fattura %s — XML generato (%d bytes), "
                "filename: %s — Nessun invio reale.",
                self.name, len(xml_content), filename,
            )
            self.l10n_it_pec_sent_date = fields.Datetime.now()
            self.l10n_it_pec_last_error = False
            self.message_post(
                body=_(
                    "🔵 <b>DEMO</b>: XML FatturaPA generato con successo "
                    "(<code>%s</code>, %d bytes). Nessun invio reale effettuato."
                ) % (filename, len(xml_content)),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
                attachment_ids=[self.l10n_it_pec_xml_attachment_id.id],
            )
            # In demo NON cambiamo lo stato EDI standard
            return

        # ── INVIO REALE (test / production) ───────────────────────────
        company._check_pec_configuration()

        destination = company._get_pec_sdi_destination()

        # Costruzione email PEC
        msg = EmailMessage()
        msg['Subject'] = filename  # SDI richiede il nome file come subject
        msg['From'] = company.l10n_it_pec_email
        msg['To'] = destination
        msg.set_content(
            f"Invio fattura elettronica {self.name} — "
            f"Modalità: {mode}"
        )

        # Allegato XML
        xml_bytes = xml_content if isinstance(xml_content, bytes) else xml_content.encode('utf-8')
        msg.add_attachment(
            xml_bytes,
            maintype='application',
            subtype='xml',
            filename=filename,
        )

        # Invio SMTP
        try:
            if company.l10n_it_pec_smtp_security == 'ssl':
                smtp = smtplib.SMTP_SSL(
                    company.l10n_it_pec_smtp_server,
                    company.l10n_it_pec_smtp_port,
                    timeout=30,
                )
            else:
                smtp = smtplib.SMTP(
                    company.l10n_it_pec_smtp_server,
                    company.l10n_it_pec_smtp_port,
                    timeout=30,
                )
                smtp.starttls()

            smtp.login(
                company.l10n_it_pec_smtp_user,
                company.l10n_it_pec_smtp_password,
            )
            smtp.send_message(msg)
            smtp.quit()

        except smtplib.SMTPException as e:
            raise UserError(
                _("Errore SMTP durante l'invio PEC:\n%s") % str(e)
            )

        # Aggiorna record
        self.l10n_it_pec_sent_date = fields.Datetime.now()
        self.l10n_it_pec_message_id = msg.get('Message-ID', '')
        self.l10n_it_pec_last_error = False

        # Aggiorna stato EDI standard
        self.l10n_it_edi_state = 'sent'

        env_label = _("TEST") if mode == 'test' else _("PRODUZIONE")
        self.message_post(
            body=_(
                "✅ Fattura inviata via PEC allo SDI [%s]\n"
                "Destinatario: <code>%s</code>\n"
                "File: <code>%s</code>\n"
                "Message-ID: <code>%s</code>"
            ) % (env_label, destination, filename, self.l10n_it_pec_message_id),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
            attachment_ids=[self.l10n_it_pec_xml_attachment_id.id],
        )

    # ══════════════════════════════════════════════════════════════════
    #  Azione manuale: Invia via PEC (bottone nella vista fattura)
    # ══════════════════════════════════════════════════════════════════

    def action_l10n_it_pec_send(self):
        """Azione bottone: invia la fattura via PEC allo SDI."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("La fattura deve essere confermata prima dell'invio."))
        if not self._l10n_it_edi_pec_is_active():
            raise UserError(
                _("La modalità PEC non è attiva. "
                  "Configurare in Impostazioni → Contabilità → PEC SDI.")
            )
        self._l10n_it_pec_send_to_sdi()

    def action_l10n_it_pec_preview_xml(self):
        """Genera e mostra l'XML senza inviare."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("La fattura deve essere confermata per generare l'XML."))

        xml_content, filename = self._l10n_it_pec_generate_xml()

        self.message_post(
            body=_(
                "👁 Anteprima XML generata: <code>%s</code> (%d bytes)"
            ) % (filename, len(xml_content)),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
            attachment_ids=[self.l10n_it_pec_xml_attachment_id.id],
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("XML Generato"),
                'message': _("File %s generato e allegato alla fattura.") % filename,
                'type': 'success',
                'sticky': False,
            },
        }

    # ══════════════════════════════════════════════════════════════════
    #  Processamento notifiche SDI ricevute via PEC
    # ══════════════════════════════════════════════════════════════════

    def _l10n_it_pec_process_sdi_notification(self, notification_type, xml_content, raw_email=None):
        """
        Processa una notifica SDI ricevuta via PEC.
        Aggiorna lo stato EDI standard (NON uno stato parallelo).

        :param notification_type: tipo notifica SDI (RC, NS, MC, AT, NE, DT)
        :param xml_content: contenuto XML della notifica
        :param raw_email: email PEC originale (per logging)
        """
        self.ensure_one()

        notification_labels = {
            'RC': _('Ricevuta di Consegna'),
            'NS': _('Notifica di Scarto'),
            'MC': _('Mancata Consegna'),
            'AT': _('Attestazione di avvenuta trasmissione'),
            'NE': _('Notifica Esito'),
            'DT': _('Decorrenza Termini'),
        }

        label = notification_labels.get(notification_type, notification_type)

        # Gestione speciale per NE (può essere accettazione o rifiuto)
        if notification_type == 'NE':
            new_state = self._l10n_it_pec_parse_ne_outcome(xml_content)
        else:
            new_state = SDI_NOTIFICATION_MAP.get(notification_type)

        if new_state:
            self.l10n_it_edi_state = new_state

        # Salva notifica come allegato
        att_name = f"SDI_{notification_type}_{self.name.replace('/', '_')}.xml"
        attachment = self.env['ir.attachment'].create({
            'name': att_name,
            'raw': xml_content if isinstance(xml_content, bytes) else xml_content.encode('utf-8'),
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/xml',
        })

        # Icona per tipo
        icon_map = {
            'RC': '✅', 'NS': '❌', 'MC': '⚠️',
            'AT': '✅', 'NE': '📋', 'DT': '⏰',
        }
        icon = icon_map.get(notification_type, 'ℹ️')

        self.message_post(
            body=_(
                "%s Notifica SDI ricevuta: <b>%s</b>\n"
                "Nuovo stato: <code>%s</code>"
            ) % (icon, label, new_state or _('invariato')),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
            attachment_ids=[attachment.id],
        )

        _logger.info(
            "Notifica SDI %s processata per fattura %s → stato: %s",
            notification_type, self.name, new_state,
        )

    def _l10n_it_pec_parse_ne_outcome(self, xml_content):
        """
        Parsifica una Notifica Esito (NE) per determinare se è
        Accettazione o Rifiuto.
        """
        try:
            content = xml_content if isinstance(xml_content, str) else xml_content.decode('utf-8')
            # Cerca il tag Esito nel XML della notifica
            # EC01 = Accettazione, EC02 = Rifiuto
            if 'EC01' in content:
                return 'delivered'
            elif 'EC02' in content:
                return 'invalid'
        except Exception:
            _logger.warning("Impossibile parsificare Notifica Esito per %s", self.name)

        return 'delivered'  # default safe: silenzio-assenso
