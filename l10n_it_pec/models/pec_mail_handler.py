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

# Pattern per estrarre l'IdentificativoSdI dal contenuto del file
# metadati. L'IdentificativoSdI è l'ID univoco assegnato dallo SDI alla
# trasmissione della fattura, fondamentale per audit e dispute.
# Il tag può comparire con o senza namespace prefix.
SDI_IDENTIFIER_PATTERN = re.compile(
    r'<(?:\w+:)?IdentificativoSdI>\s*([^<\s]+)\s*</(?:\w+:)?IdentificativoSdI>',
    re.IGNORECASE,
)

# Pattern per estrarre il P.IVA del CessionarioCommittente (destinatario)
# dalla fattura passiva. Cerca il tag IdCodice all'interno del blocco
# CessionarioCommittente/DatiAnagrafici/IdFiscaleIVA.
SDI_DEST_VAT_PATTERN = re.compile(
    r'<CessionarioCommittente>.*?'
    r'<IdFiscaleIVA>.*?<IdCodice>\s*([^<\s]+)\s*</IdCodice>',
    re.IGNORECASE | re.DOTALL,
)

# Pattern alternativo: CodiceFiscale del CessionarioCommittente
# (per persone fisiche o se manca P.IVA).
SDI_DEST_CF_PATTERN = re.compile(
    r'<CessionarioCommittente>.*?'
    r'<CodiceFiscale>\s*([^<\s]+)\s*</CodiceFiscale>',
    re.IGNORECASE | re.DOTALL,
)

# Pattern per estrarre il P.IVA del trasmittente dal filename di una notifica SDI.
# Esempio: IT01879020517_00001_RC_001.xml → estrae "01879020517"
SDI_NOTIF_VAT_FROM_FILENAME = re.compile(
    r'^[A-Z]{2}([A-Z0-9]+)_',
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
                    processed = self._process_pec_message(imap, msg_id, company)
                    if not processed:
                        # Il messaggio non era destinato a questa company:
                        # rimuovi flag SEEN per lasciarlo disponibile alle altre.
                        try:
                            imap.store(msg_id, '-FLAGS', '\\Seen')
                        except Exception as e:
                            _logger.warning(
                                "Impossibile resettare flag UNSEEN per msg %s: %s",
                                msg_id, str(e),
                            )
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
        """Processa un singolo messaggio PEC dallo SDI.

        Ritorna:
        - True se il messaggio è stato processato per questa company
          (almeno un allegato era destinato a questa company)
        - False se nessun allegato era destinato a questa company
          (la mail va lasciata UNSEEN per altre company)
        """
        status, msg_data = imap.fetch(msg_id, '(RFC822)')
        if status != 'OK':
            return False

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
            return False

        # Flag: almeno un allegato è stato processato per questa company
        any_processed = False

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
                # Verifica se la notifica è per questa company
                if not self._notification_is_for_company(filename, company):
                    _logger.info(
                        "Notifica %s non destinata a company %s, skip.",
                        filename, company.name,
                    )
                    continue
                notif_type = notif_match.group(1).upper()
                self._handle_sdi_notification(
                    notif_type, content, filename, company,
                )
                any_processed = True
            elif SDI_PASSIVE_INVOICE_PATTERN.match(filename):
                # È una fattura passiva ricevuta.
                # Verifica se la fattura è destinata a questa company
                if not self._passive_invoice_is_for_company(content, company):
                    _logger.info(
                        "Fattura passiva %s non destinata a company %s, skip.",
                        filename, company.name,
                    )
                    continue
                # Cerca tra gli altri allegati il file metadati
                # corrispondente per estrarre l'IdentificativoSdI.
                sdi_identifier = self._find_sdi_identifier_for_invoice(
                    invoice_filename=filename,
                    all_attachments=xml_attachments,
                )
                self._handle_passive_invoice(
                    content, filename, company,
                    raw_email=raw_email, subject=subject,
                    sdi_identifier=sdi_identifier,
                )
                any_processed = True
            else:
                _logger.info(
                    "Allegato XML non riconosciuto: %s", filename
                )

        return any_processed

    # ══════════════════════════════════════════════════════════════════
    #  Helper: filtraggio destinatario
    # ══════════════════════════════════════════════════════════════════

    def _normalize_vat(self, value):
        """Normalizza un identificativo fiscale per il confronto:
        rimuove prefisso paese (IT) e converte in maiuscolo."""
        if not value:
            return ''
        v = str(value).strip().upper()
        if v.startswith('IT') and len(v) > 2:
            v = v[2:]
        return v

    def _notification_is_for_company(self, filename, company):
        """Verifica se la notifica SDI nel filename è destinata a questa company.
        Il P.IVA del trasmittente è nel filename (primo blocco dopo IT)."""
        match = SDI_NOTIF_VAT_FROM_FILENAME.match(filename)
        if not match:
            # Se non riusciamo a estrarre il P.IVA, processiamo per backward compat
            return True
        notif_vat = self._normalize_vat(match.group(1))
        company_vat = self._normalize_vat(company.vat)
        company_cf = self._normalize_vat(company.l10n_it_codice_fiscale)
        return notif_vat in (company_vat, company_cf)

    def _passive_invoice_is_for_company(self, xml_content, company):
        """Verifica se la fattura passiva è destinata a questa company.
        Estrae il P.IVA o CodiceFiscale del CessionarioCommittente dall'XML."""
        try:
            content = xml_content if isinstance(xml_content, str) else xml_content.decode('utf-8', errors='replace')
        except Exception:
            return True  # Se non riusciamo a leggere, processiamo per backward compat

        company_vat = self._normalize_vat(company.vat)
        company_cf = self._normalize_vat(company.l10n_it_codice_fiscale)

        # Cerca P.IVA destinatario
        match = SDI_DEST_VAT_PATTERN.search(content)
        if match:
            dest_vat = self._normalize_vat(match.group(1))
            if dest_vat in (company_vat, company_cf):
                return True

        # Cerca Codice Fiscale destinatario
        match = SDI_DEST_CF_PATTERN.search(content)
        if match:
            dest_cf = self._normalize_vat(match.group(1))
            if dest_cf in (company_vat, company_cf):
                return True

        # Se né P.IVA né CF sono presenti nell'XML, non possiamo decidere:
        # processiamo per backward compat (raro caso edge).
        if not SDI_DEST_VAT_PATTERN.search(content) and not SDI_DEST_CF_PATTERN.search(content):
            return True

        return False

    def _find_sdi_identifier_for_invoice(self, invoice_filename, all_attachments):
        """Cerca il file metadati SDI accluso al messaggio PEC e ne
        estrae l'IdentificativoSdI.

        Lo SDI accompagna ogni fattura recapitata via PEC con un file
        metadati `IT...._MT_NNN.xml` (o `_metadati.xml` nella forma
        canonica) che contiene tra le altre cose il tag
        `<IdentificativoSdI>`. Questo identifier è l'ID univoco della
        trasmissione e ci serve per audit e dispute con il fornitore.

        Strategia:
        1. Filtra dagli allegati quelli che matchano il pattern metadati.
        2. Se ce n'è uno solo (caso normale: 1 fattura + 1 metadati nel
           messaggio PEC), usa quello senza altre verifiche.
        3. Se ce ne sono di più, prova a fare match per prefisso col
           filename della fattura (rimuovendo l'estensione).
        4. Estrai il tag IdentificativoSdI con regex.

        Ritorna `None` se il file metadati non è presente, è illeggibile,
        o non contiene il tag.
        """
        metadata_attachments = [
            a for a in all_attachments
            if SDI_METADATA_FILENAME_PATTERN.search(a['filename'])
        ]
        if not metadata_attachments:
            return None

        chosen = None
        if len(metadata_attachments) == 1:
            chosen = metadata_attachments[0]
        else:
            # Più metadati nello stesso messaggio: match per prefisso.
            # IT01234567890_00001.xml.p7m → cerca IT01234567890_00001 in metadati.
            invoice_base = invoice_filename
            for ext in ('.xml.p7m', '.xml', '.XML.P7M', '.XML'):
                if invoice_base.endswith(ext):
                    invoice_base = invoice_base[:-len(ext)]
                    break
            for meta in metadata_attachments:
                if meta['filename'].startswith(invoice_base):
                    chosen = meta
                    break
            # Fallback: prendi il primo
            if chosen is None:
                chosen = metadata_attachments[0]

        return self._extract_sdi_identifier_from_metadata(chosen['content'])

    def _extract_sdi_identifier_from_metadata(self, xml_content):
        """Estrae il valore del tag <IdentificativoSdI> dal contenuto
        di un file metadati FatturaPA.

        Volutamente robusto: accetta sia bytes che str, accetta
        namespace prefix opzionale, e in caso di parsing fallito
        ritorna None senza sollevare (un identifier mancante NON deve
        bloccare l'import della fattura).
        """
        try:
            content = (
                xml_content.decode('utf-8', errors='replace')
                if isinstance(xml_content, bytes)
                else xml_content
            )
            match = SDI_IDENTIFIER_PATTERN.search(content)
            if match:
                return match.group(1).strip()
        except Exception as e:
            _logger.warning(
                "Impossibile estrarre IdentificativoSdI dal metadata: %s", e,
            )
        return None

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
                                raw_email=None, subject=None,
                                sdi_identifier=None):
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
        - IdentificativoSdI: se estratto dal file metadati allegato al
          messaggio PEC, viene scritto sul campo
          `l10n_it_pec_sdi_identifier` della fattura importata.
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
        # Una fattura passiva PEC è già stata importata se:
        # 1. Esiste un ir.attachment con lo stesso filename collegato a
        #    una account.move della stessa company, OPPURE
        # 2. Esiste una account.move con lo stesso IdentificativoSdI
        #    nella stessa company (chiave univoca di trasmissione SDI).
        if sdi_identifier:
            existing_by_sdi = self.env['account.move'].search([
                ('l10n_it_pec_sdi_identifier', '=', sdi_identifier),
                ('company_id', '=', company.id),
            ], limit=1)
            if existing_by_sdi:
                _logger.info(
                    "Fattura passiva %s già importata (move %s, SDI: %s), skip.",
                    filename, existing_by_sdi.name or existing_by_sdi.id,
                    sdi_identifier,
                )
                return

        # Deduplica per filename (fallback se SDI identifier mancante)
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
        # Replichiamo il pattern ufficiale usato dal codice standard
        # di l10n_it_edi in account_move.py (righe 239-240 e 972):
        #
        #   self.invalidate_recordset(fnames=[
        #       'l10n_it_edi_attachment_id', 'l10n_it_edi_attachment_file'])
        #   self.message_post(attachment_ids=self.l10n_it_edi_attachment_id.ids)
        #   self._extend_with_attachments(self.l10n_it_edi_attachment_id, new=True)
        #
        # Il punto cruciale è che il decoder FatturaPA viene agganciato
        # passando l'attachment *tramite il campo computed*
        # `l10n_it_edi_attachment_id`, non direttamente. Il campo viene
        # popolato automaticamente quando l'attachment viene creato con
        # res_field='l10n_it_edi_attachment_file'.
        #
        # Se dopo questo giro la move non ha partner_id valorizzato,
        # il parser non si è agganciato: quarantena.
        created_moves = self.env['account.move']
        import_error = None
        try:
            move = self.env['account.move'].with_company(company).create({
                'move_type': 'in_invoice',
            })
            self.env['ir.attachment'].sudo().with_company(company).create({
                'name': filename,
                'raw': xml_bytes,
                'type': 'binary',
                'res_model': 'account.move',
                'res_id': move.id,
                'res_field': 'l10n_it_edi_attachment_file',
            })

            # Invalida i campi computed per forzare il re-link dell'attachment
            move.invalidate_recordset(fnames=[
                'l10n_it_edi_attachment_id',
                'l10n_it_edi_attachment_file',
            ])

            edi_attachment = move.l10n_it_edi_attachment_id
            move.with_context(
                account_predictive_bills_disable_prediction=True,
                no_new_invoice=True,
            ).message_post(attachment_ids=edi_attachment.ids)

            # Chiama esplicitamente il decoder FatturaPA.
            # Questo è il passaggio chiave che la message_post da sola
            # non fa scattare da codice (funziona solo dall'UI).
            move._extend_with_attachments(edi_attachment, new=True)

            # Verifica che il parser abbia popolato la move.
            move.invalidate_recordset(['partner_id', 'invoice_line_ids'])
            if move.partner_id:
                created_moves = move
            else:
                import_error = (
                    "il parser FatturaPA non ha popolato la fattura "
                    "(partner_id vuoto dopo _extend_with_attachments)"
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

        # Scrive l'IdentificativoSdI estratto dal file metadati,
        # se disponibile. Una sola scrittura, vale per tutte le move
        # create da questo XML (di norma una sola).
        if sdi_identifier:
            try:
                created_moves.write({
                    'l10n_it_pec_sdi_identifier': sdi_identifier,
                })
                _logger.info(
                    "IdentificativoSdI %s salvato su fattura %s",
                    sdi_identifier, filename,
                )
            except Exception as e:
                _logger.warning(
                    "Impossibile salvare IdentificativoSdI %s "
                    "sulla fattura %s: %s",
                    sdi_identifier, filename, e,
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
