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

# Pattern per fatture passive ricevute.
# Accetta sia XML puro sia CAdES (.xml.p7m). Il filename segue lo schema
# FatturaPA: <CodicePaese><IdentificativoFiscale>_<Progressivo>.xml[.p7m]
# Esempi validi:  IT01234567890_00001.xml , IT01234567890_ABCDE.xml.p7m
# La guard sul file metadati è gestita separatamente in _process_pec_message
# tramite SDI_METADATA_FILENAME_PATTERN per evitare falsi positivi.
SDI_PASSIVE_INVOICE_PATTERN = re.compile(
    r'^[A-Z]{2}[A-Z0-9]{2,28}_[A-Z0-9]+\.xml(\.p7m)?$',
    re.IGNORECASE,
)

# Pattern per il file metadati SDI che accompagna ogni fattura passiva.
# Esempio canonico: IT01234567890_00001_metadati.xml
# Esempio alternativo (Aruba e altri): IT01234567890_00001_MT_001.xml
# Questo file NON è una fattura e non deve mai essere passato al motore
# di import standard.
SDI_METADATA_FILENAME_PATTERN = re.compile(
    r'(_metadati|_MT_\d+)\.xml$',
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
        # Cerca company con PEC attiva O company che hanno fatture PEC
        # ancora in attesa (per gestire il caso in cui PEC viene disabilitata
        # dopo l'invio ma ci sono ancora notifiche SDI da ricevere).
        active_companies = self.env['res.company'].search([
            ('l10n_it_edi_pec_mode', 'in', ('test', 'production')),
            ('l10n_it_pec_imap_server', '!=', False),
        ])
        pending_pec_moves = self.env['account.move'].search([
            ('l10n_it_edi_state', 'in', ('being_sent', 'processing', 'forward_attempt')),
            '|',
            ('l10n_it_edi_transaction', '=like', '<%'),
            ('l10n_it_edi_transaction', '=like', 'pec_%'),
        ])
        pending_companies = pending_pec_moves.mapped('company_id').filtered(
            lambda c: c.l10n_it_pec_imap_server
        )
        companies = active_companies | pending_companies

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

            # Scarta esplicitamente i file di metadati SDI:
            # accompagnano le fatture passive ma non sono fatture.
            if SDI_METADATA_FILENAME_PATTERN.search(filename):
                _logger.info(
                    "Ignorato file metadati SDI: %s", filename,
                )
                continue

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
                    raw_email=raw_email, subject=subject,
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

    def _handle_passive_invoice(self, xml_content, filename, company,
                                raw_email=None, subject=None):
        """
        Gestisce una fattura passiva ricevuta via PEC dallo SDI.
        Importa l'XML e crea la fattura fornitore in bozza.

        Garanzie:
        - Deduplica sul filename: se esiste già un ir.attachment con lo
          stesso nome collegato a una account.move della stessa company,
          il messaggio viene ignorato.
        - Quarantena in caso di errore: se l'import standard fallisce o
          non crea alcuna fattura, l'XML originale viene comunque salvato
          come ir.attachment "orfano" con un tag di quarantena, così non
          si perde mai il documento.
        - Archivio .eml: se disponibile, il messaggio PEC originale viene
          allegato alla fattura importata per audit/conservazione.
        """
        _logger.info(
            "Fattura passiva ricevuta: %s (company: %s)",
            filename, company.name,
        )

        xml_bytes = (
            xml_content if isinstance(xml_content, bytes)
            else xml_content.encode('utf-8')
        )

        # ── Deduplica ─────────────────────────────────────────────────
        # Se un attachment con lo stesso nome è già collegato a una
        # account.move della stessa company, la fattura è già stata
        # importata in un giro precedente del cron: non rifare nulla.
        existing = self.env['ir.attachment'].search([
            ('name', '=', filename),
            ('res_model', '=', 'account.move'),
        ], limit=1)
        if existing:
            existing_move = self.env['account.move'].browse(existing.res_id)
            if existing_move.exists() and existing_move.company_id == company:
                _logger.info(
                    "Fattura passiva %s già importata (move %s), skip.",
                    filename, existing_move.name or existing_move.id,
                )
                return

        # ── Import tramite il parser standard l10n_it_edi ─────────────
        # Strategia: replichiamo il pattern usato da Odoo CE nel metodo
        # standard `_l10n_it_edi_create_move_with_attachment`, ma senza
        # passare per il proxy IAP (non abbiamo un proxy_user e il file
        # non è criptato, arriva in chiaro dalla PEC).
        #
        # 1) creiamo una account.move vuota con la company corretta
        # 2) creiamo un ir.attachment con res_field='l10n_it_edi_attachment_file'
        #    e collegato alla move: questo è il campo speciale che fa
        #    scattare il decoder FatturaPA di Odoo
        # 3) chiamiamo move.message_post(attachment_ids=[...]) che invoca
        #    gli hook di _extend_with_attachments e popola la move
        #
        # Se dopo il message_post la move non ha partner_id valorizzato,
        # consideriamo l'import fallito e mandiamo tutto in quarantena.
        created_moves = self.env['account.move']
        import_error = None
        try:
            move = self.env['account.move'].with_company(company).create({
                'move_type': 'in_invoice',
            })
            attachment = self.env['ir.attachment'].sudo().with_company(company).create({
                'name': filename,
                'raw': xml_bytes,
                'type': 'binary',
                'res_model': 'account.move',
                'res_id': move.id,
                'res_field': 'l10n_it_edi_attachment_file',
            })
            move.with_context(
                account_predictive_bills_disable_prediction=True,
                no_new_invoice=True,
            ).message_post(attachment_ids=attachment.ids)

            # Verifica che il parser abbia popolato la move.
            # Se partner_id è ancora vuoto significa che il decoder
            # FatturaPA non si è agganciato o non ha riconosciuto il file.
            move.invalidate_recordset(['partner_id', 'invoice_line_ids'])
            if move.partner_id:
                created_moves = move
            else:
                import_error = (
                    "il parser FatturaPA non ha popolato la fattura "
                    "(partner_id vuoto dopo message_post)"
                )
                # Cancella la move vuota per non sporcare il db.
                move.with_context(force_delete=True).unlink()
        except Exception as e:
            import_error = str(e)
            _logger.exception(
                "Errore importazione fattura passiva %s: %s",
                filename, import_error,
            )

        if not created_moves:
            _logger.warning(
                "Importazione fattura passiva %s: nessuna fattura creata",
                filename,
            )
            self._quarantine_passive_invoice(
                xml_bytes, filename, company,
                reason=import_error or "nessuna fattura creata dall'import standard",
            )
            return

        _logger.info(
            "Fattura passiva importata con successo: %s → %s",
            filename,
            ', '.join(m.name or f"(draft #{m.id})" for m in created_moves),
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

            # ── Allegato .eml per conservazione/audit ─────────────────
            if raw_email:
                try:
                    eml_name = self._build_eml_filename(filename, subject)
                    self.env['ir.attachment'].create({
                        'name': eml_name,
                        'raw': raw_email if isinstance(raw_email, bytes) else raw_email.encode('utf-8'),
                        'mimetype': 'message/rfc822',
                        'res_model': 'account.move',
                        'res_id': move.id,
                    })
                except Exception as e:
                    _logger.warning(
                        "Impossibile allegare .eml originale alla fattura "
                        "%s: %s", move.name or move.id, e,
                    )

    def _build_eml_filename(self, xml_filename, subject):
        """Costruisce un nome file per l'archivio .eml del messaggio PEC."""
        base = xml_filename.rsplit('.xml', 1)[0]
        return f"{base}_pec.eml"

    def _quarantine_passive_invoice(self, xml_bytes, filename, company, reason):
        """
        Salva l'XML come attachment "orfano" con un tag di quarantena.

        Non viene collegato a nessuna account.move (res_model/res_id
        lasciati vuoti) così resta visibile nell'area allegati e può
        essere ispezionato manualmente. Evita la perdita definitiva
        del documento quando il motore di import standard fallisce.
        """
        try:
            self.env['ir.attachment'].create({
                'name': f"QUARANTINE_{filename}",
                'raw': xml_bytes,
                'mimetype': 'application/xml',
                'description': _(
                    "Fattura passiva PEC in quarantena (company: %(company)s). "
                    "Motivo: %(reason)s"
                ) % {'company': company.name, 'reason': reason},
            })
            _logger.warning(
                "Fattura passiva %s posta in quarantena (company %s): %s",
                filename, company.name, reason,
            )
        except Exception as e:
            _logger.exception(
                "Impossibile mettere in quarantena la fattura passiva %s: %s",
                filename, e,
            )
