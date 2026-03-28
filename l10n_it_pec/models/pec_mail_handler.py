# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import email
import imaplib
import logging
import re
from email import policy

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

# Pattern per identificare il tipo di notifica SDI dal nome file allegato
# Esempio: IT01234567890_12345_RC_001.xml
SDI_NOTIFICATION_PATTERN = re.compile(
    r'(?:IT\d+_\w+_)?'  # prefisso opzionale
    r'(RC|NS|MC|AT|NE|DT)'  # tipo notifica
    r'_?\d*\.xml',
    re.IGNORECASE,
)

# Pattern per estrarre il nome file fattura dalla notifica SDI
SDI_INVOICE_REF_PATTERN = re.compile(
    r'<NomeFile>(.*?)</NomeFile>',
    re.IGNORECASE,
)

# Pattern per fatture passive ricevute
SDI_PASSIVE_INVOICE_PATTERN = re.compile(
    r'IT\d{11}_\w+\.xml',
    re.IGNORECASE,
)


class PecMailHandler(models.AbstractModel):
    _name = 'l10n_it_pec.mail.handler'
    _description = 'Gestore PEC SDI - Polling IMAP'

    # ══════════════════════════════════════════════════════════════════
    #  Cron: polling inbox PEC
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _cron_poll_pec_inbox(self):
        """
        Cron job: controlla l'inbox PEC per notifiche SDI
        e fatture passive in ingresso.

        Eseguito per ogni company che ha PEC attiva.
        """
        companies = self.env['res.company'].search([
            ('l10n_it_edi_pec_mode', 'in', ('test', 'production')),
            ('l10n_it_pec_imap_server', '!=', False),
        ])

        for company in companies:
            try:
                self._poll_company_pec(company)
            except Exception as e:
                _logger.exception(
                    "Errore polling PEC per company %s: %s",
                    company.name, str(e),
                )

    def _poll_company_pec(self, company):
        """Polling IMAP per una singola company."""
        _logger.info(
            "Polling PEC inbox per %s (%s)",
            company.name, company.l10n_it_pec_email,
        )

        imap_user = company.l10n_it_pec_imap_user or company.l10n_it_pec_smtp_user
        imap_password = company.l10n_it_pec_imap_password or company.l10n_it_pec_smtp_password

        if not imap_user or not imap_password:
            _logger.warning("Credenziali IMAP mancanti per %s", company.name)
            return

        try:
            imap = imaplib.IMAP4_SSL(
                company.l10n_it_pec_imap_server,
                company.l10n_it_pec_imap_port or 993,
            )
            imap.login(imap_user, imap_password)
            imap.select('INBOX')
        except Exception as e:
            _logger.error("Connessione IMAP fallita per %s: %s", company.name, e)
            return

        try:
            # Cerca email non lette dallo SDI
            search_criteria = '(UNSEEN FROM "@pec.fatturapa.it")'
            status, msg_ids = imap.search(None, search_criteria)

            if status != 'OK' or not msg_ids[0]:
                _logger.info("Nessun nuovo messaggio SDI per %s", company.name)
                return

            message_ids = msg_ids[0].split()
            _logger.info(
                "Trovati %d messaggi SDI per %s",
                len(message_ids), company.name,
            )

            for msg_id in message_ids:
                try:
                    self._process_pec_message(imap, msg_id, company)
                except Exception as e:
                    _logger.exception(
                        "Errore processamento messaggio PEC %s: %s",
                        msg_id, str(e),
                    )

        finally:
            try:
                imap.close()
                imap.logout()
            except Exception:
                pass

    def _process_pec_message(self, imap, msg_id, company):
        """Processa un singolo messaggio PEC dallo SDI."""
        status, msg_data = imap.fetch(msg_id, '(RFC822)')
        if status != 'OK':
            return

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email, policy=policy.default)

        subject = msg.get('Subject', '')
        from_addr = msg.get('From', '')

        _logger.info(
            "Processamento PEC: subject=%s, from=%s",
            subject, from_addr,
        )

        # Estrai allegati XML
        xml_attachments = []
        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()

            if filename and (
                filename.lower().endswith('.xml')
                or filename.lower().endswith('.xml.p7m')
            ):
                payload = part.get_payload(decode=True)
                if payload:
                    xml_attachments.append({
                        'filename': filename,
                        'content': payload,
                    })

        if not xml_attachments:
            _logger.info("Nessun allegato XML nel messaggio PEC")
            return

        for attachment in xml_attachments:
            filename = attachment['filename']
            content = attachment['content']

            # Identifica tipo di messaggio
            notif_match = SDI_NOTIFICATION_PATTERN.search(filename)

            if notif_match:
                # È una notifica SDI (RC, NS, MC, AT, NE, DT)
                notif_type = notif_match.group(1).upper()
                self._handle_sdi_notification(
                    notif_type, content, filename, company,
                )
            elif SDI_PASSIVE_INVOICE_PATTERN.match(filename):
                # È una fattura passiva ricevuta
                self._handle_passive_invoice(
                    content, filename, company,
                )
            else:
                _logger.info(
                    "Allegato XML non riconosciuto: %s", filename
                )

    # ══════════════════════════════════════════════════════════════════
    #  Gestione notifiche SDI
    # ══════════════════════════════════════════════════════════════════

    def _handle_sdi_notification(self, notif_type, xml_content, filename, company):
        """
        Gestisce una notifica SDI ricevuta.
        Cerca la fattura correlata e aggiorna lo stato EDI standard.
        """
        _logger.info(
            "Notifica SDI %s ricevuta: %s (company: %s)",
            notif_type, filename, company.name,
        )

        # Cerca il riferimento alla fattura originale nel XML della notifica
        invoice_ref = self._extract_invoice_reference(xml_content)

        if not invoice_ref:
            _logger.warning(
                "Impossibile estrarre riferimento fattura da notifica %s",
                filename,
            )
            return

        # Cerca la fattura nel database
        move = self._find_invoice_by_reference(invoice_ref, company)

        if not move:
            _logger.warning(
                "Fattura non trovata per riferimento '%s' (notifica %s)",
                invoice_ref, filename,
            )
            return

        # Processa la notifica sulla fattura
        move._l10n_it_pec_process_sdi_notification(
            notif_type, xml_content,
        )

    def _extract_invoice_reference(self, xml_content):
        """
        Estrae il riferimento alla fattura originale dal XML della notifica SDI.
        Cerca il tag <NomeFile> che contiene il nome del file fattura inviato.
        """
        try:
            content = xml_content if isinstance(xml_content, str) else xml_content.decode('utf-8')
            match = SDI_INVOICE_REF_PATTERN.search(content)
            if match:
                return match.group(1).replace('.xml', '').replace('.p7m', '')
        except Exception:
            pass
        return None

    def _find_invoice_by_reference(self, reference, company):
        """
        Cerca una fattura nel database per riferimento.
        Il riferimento può essere il nome file XML o il nome fattura.
        """
        # Cerca per nome file nell'allegato XML PEC
        attachment = self.env['ir.attachment'].search([
            ('name', 'like', reference),
            ('res_model', '=', 'account.move'),
        ], limit=1)

        if attachment:
            return self.env['account.move'].browse(attachment.res_id)

        # Cerca per nome fattura (normalizza separatori)
        normalized_ref = reference.replace('_', '/')
        move = self.env['account.move'].search([
            ('name', '=', normalized_ref),
            ('company_id', '=', company.id),
        ], limit=1)

        if move:
            return move

        # Cerca per pec_message_id correlato
        # (alcune notifiche SDI hanno l'In-Reply-To del messaggio originale)
        return None

    # ══════════════════════════════════════════════════════════════════
    #  Gestione fatture passive
    # ══════════════════════════════════════════════════════════════════

    def _handle_passive_invoice(self, xml_content, filename, company):
        """
        Gestisce una fattura passiva ricevuta via PEC dallo SDI.
        Importa l'XML e crea la fattura fornitore in bozza.
        """
        _logger.info(
            "Fattura passiva ricevuta: %s (company: %s)",
            filename, company.name,
        )

        try:
            # Usa il motore di importazione standard di l10n_it_edi
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'raw': xml_content if isinstance(xml_content, bytes) else xml_content.encode('utf-8'),
                'mimetype': 'application/xml',
            })

            # Prova ad importare usando il decoder standard
            moves = self.env['account.move'].with_company(company)
            created_moves = moves._l10n_it_edi_import_invoices([attachment])

            if created_moves:
                _logger.info(
                    "Fattura passiva importata con successo: %s → %s",
                    filename,
                    ', '.join(created_moves.mapped('name')),
                )
                for move in created_moves:
                    move.message_post(
                        body=_(
                            "📥 Fattura fornitore importata automaticamente "
                            "da PEC SDI: <code>%s</code>"
                        ) % filename,
                        message_type='notification',
                        subtype_xmlid='mail.mt_note',
                    )
            else:
                _logger.warning(
                    "Importazione fattura passiva %s: nessuna fattura creata",
                    filename,
                )

        except Exception as e:
            _logger.exception(
                "Errore importazione fattura passiva %s: %s",
                filename, str(e),
            )
