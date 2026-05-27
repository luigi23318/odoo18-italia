# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import logging
import smtplib
from base64 import b64decode
from email.message import EmailMessage

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Mapping notifiche SDI → stato l10n_it_edi nativo Odoo 18
# RC  = Ricevuta di Consegna         → forwarded (accettata e consegnata)
# NS  = Notifica di Scarto           → rejected (XML non valido)
# MC  = Mancata Consegna             → forward_failed (consegna fallita)
# AT  = Attestazione                  → forwarded
# NE  = Notifica Esito (accettata)   → accepted_by_pa_partner
# NE  = Notifica Esito (rifiutata)   → rejected_by_pa_partner
# DT  = Decorrenza Termini           → accepted_by_pa_partner_after_expiry (silenzio-assenso)
SDI_NOTIFICATION_MAP = {
    'RC': 'forwarded',
    'NS': 'rejected',
    'MC': 'forward_failed',
    'AT': 'forwarded',
    'DT': 'accepted_by_pa_partner_after_expiry',
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
    l10n_it_pec_signed_attachment_id = fields.Many2one(
        'ir.attachment',
        string="XML firmato digitalmente",
        copy=False,
        help="File XML firmato digitalmente (CAdES .p7m o XAdES .xml) da inviare allo SDI",
    )
    l10n_it_pec_signature_required = fields.Boolean(
        string="Firma digitale richiesta",
        compute='_compute_l10n_it_pec_signature_required',
        help="True se la fattura è destinata alla PA e richiede firma digitale",
    )
    l10n_it_pec_signature_state = fields.Selection(
        selection=[
            ('not_required', 'Non richiesta'),
            ('awaiting', 'In attesa di firma'),
            ('signed', 'Firmato'),
        ],
        string="Stato firma digitale",
        compute='_compute_l10n_it_pec_signature_state',
    )
    l10n_it_pec_sdi_identifier = fields.Char(
        string='Identificativo SdI',
        readonly=True,
        copy=False,
        index=True,
        help="Identificativo univoco assegnato dal Sistema di Interscambio "
             "alla trasmissione della fattura. Estratto dal file metadati "
             "(_MT_NNN.xml) accluso al messaggio PEC dallo SDI. "
             "Utile per audit, conservazione sostitutiva e dispute con il "
             "fornitore.",
    )

    # ── Reset stato EDI (solo modalità test) ─────────────────────────
    l10n_it_pec_show_reset_edi = fields.Boolean(
        compute='_compute_l10n_it_pec_show_reset_edi',
    )

    @api.depends('l10n_it_edi_transaction', 'state')
    def _compute_l10n_it_pec_show_reset_edi(self):
        for move in self:
            move.l10n_it_pec_show_reset_edi = (
                move.company_id.l10n_it_edi_pec_mode == 'test'
                and move.state == 'posted'
                and bool(move.l10n_it_edi_transaction)
            )

    def action_l10n_it_pec_reset_edi(self):
        """Resetta lo stato EDI per consentire il ritorno a bozza.
        Disponibile solo in modalità test PEC."""
        self.ensure_one()
        if self.company_id.l10n_it_edi_pec_mode != 'test':
            raise UserError(_(
                "L'annullamento dello stato EDI è consentito solo in modalità test."
            ))
        self.write({
            'l10n_it_edi_state': False,
            'l10n_it_edi_transaction': False,
            'l10n_it_edi_header': False,
        })
        self.message_post(
            body=_("Stato EDI resettato manualmente (modalità test). "
                   "La fattura può ora essere riportata a bozza.")
        )

    # ══════════════════════════════════════════════════════════════════
    #  Reset campi PEC quando si torna in bozza
    # ══════════════════════════════════════════════════════════════════

    def button_draft(self):
        """Pulisce i campi PEC quando la fattura torna in bozza."""
        # Rimuove file firmato (l'XML potrebbe cambiare dopo ri-conferma)
        for move in self:
            if move.l10n_it_pec_signed_attachment_id:
                move.l10n_it_pec_signed_attachment_id.unlink()
        res = super().button_draft()
        self.write({
            'l10n_it_pec_sent_date': False,
            'l10n_it_pec_message_id': False,
            'l10n_it_pec_xml_attachment_id': False,
            'l10n_it_pec_last_error': False,
            'l10n_it_pec_signed_attachment_id': False,
        })
        return res

    # ══════════════════════════════════════════════════════════════════
    #  Firma digitale PA
    # ══════════════════════════════════════════════════════════════════

    @api.depends('commercial_partner_id.l10n_it_pa_index')
    def _compute_l10n_it_pec_signature_required(self):
        for move in self:
            move.l10n_it_pec_signature_required = move._l10n_it_pec_is_pa_invoice()

    @api.depends('l10n_it_pec_signature_required', 'l10n_it_pec_signed_attachment_id')
    def _compute_l10n_it_pec_signature_state(self):
        for move in self:
            if not move.l10n_it_pec_signature_required:
                move.l10n_it_pec_signature_state = 'not_required'
            elif move.l10n_it_pec_signed_attachment_id:
                move.l10n_it_pec_signature_state = 'signed'
            else:
                move.l10n_it_pec_signature_state = 'awaiting'

    def _l10n_it_pec_is_pa_invoice(self):
        """Determina se la fattura è destinata a una Pubblica Amministrazione.
        Codici IPA della PA sono di 6 caratteri alfanumerici maiuscoli.
        """
        self.ensure_one()
        pa_index = self.commercial_partner_id.l10n_it_pa_index or ''
        return bool(pa_index) and len(pa_index) == 6 and pa_index.isalnum() and pa_index.isupper()

    def action_l10n_it_pec_download_xml(self):
        """Scarica l'XML della fattura per la firma digitale in locale."""
        self.ensure_one()
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
            ('name', '=like', 'IT%.xml'),
        ], limit=1, order='create_date desc')

        if not attachment:
            raise UserError(_("Nessun file XML trovato per questa fattura. "
                              "Generare prima il file XML tramite 'Invia e Stampa'."))

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_l10n_it_pec_upload_signed(self):
        """Apre il wizard per caricare il file XML firmato digitalmente."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Carica XML firmato"),
            'res_model': 'l10n_it_pec.upload.signed.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_l10n_it_pec_remove_signed(self):
        """Rimuove il file XML firmato per consentire un nuovo upload."""
        self.ensure_one()
        if self.l10n_it_pec_signed_attachment_id:
            self.l10n_it_pec_signed_attachment_id.unlink()
            self.l10n_it_pec_signed_attachment_id = False

    # ══════════════════════════════════════════════════════════════════
    #  Override nome file XML: Codice Fiscale o Partita IVA
    # ══════════════════════════════════════════════════════════════════

    def _l10n_it_edi_generate_filename(self):
        """Override: usa la Partita IVA nel filename se configurato nelle impostazioni PEC."""
        company = self.company_id._l10n_it_get_edi_company()
        if company.l10n_it_pec_filename_id_type == 'partita_iva':
            a = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
            n = self.env['ir.sequence'].with_company(company).next_by_code(
                'l10n_it_edi.fattura_filename'
            )
            if not n:
                offset = 62 ** 4
                sequence = self.env['ir.sequence'].sudo().create({
                    'name': 'FatturaPA Filename Sequence',
                    'code': 'l10n_it_edi.fattura_filename',
                    'company_id': company.id,
                    'number_next': offset,
                })
                n = sequence._next()
            n = int(''.join(filter(lambda c: c.isdecimal(), n)))
            progressive_number = ""
            while n:
                (n, m) = divmod(n, len(a))
                progressive_number = a[m] + progressive_number

            # Usa la partita IVA (senza prefisso paese)
            vat = company.vat or ''
            if vat.startswith(company.country_id.code or 'IT'):
                vat = vat[2:]

            return '%(country_code)s%(vat)s_%(progressive_number)s.xml' % {
                'country_code': company.country_id.code,
                'vat': vat,
                'progressive_number': progressive_number.zfill(5),
            }
        return super()._l10n_it_edi_generate_filename()

    # ══════════════════════════════════════════════════════════════════
    #  CUORE OPZIONE C: Intercettazione del trasporto EDI
    # ══════════════════════════════════════════════════════════════════

    def _l10n_it_edi_pec_is_active(self):
        """Verifica se la modalità PEC è attiva per questa fattura.
        Con il modulo installato, PEC è sempre attiva (non esiste più 'disabled').
        """
        self.ensure_one()
        return bool(self.company_id.l10n_it_edi_pec_mode)

    def _l10n_it_pec_is_pec_transaction(self):
        """Verifica se la transaction corrente è stata generata dall'invio PEC.
        Le transaction PEC iniziano con '<' (Message-ID SMTP) o 'pec_' (fallback).
        Non include 'demo' perchè anche il proxy standard usa 'demo' come transaction.
        """
        self.ensure_one()
        t = self.l10n_it_edi_transaction or ''
        return t.startswith(('<', 'pec_'))

    def action_check_l10n_it_edi(self):
        """Override: per fatture inviate via PEC, controlla via IMAP invece del proxy SDI.
        La discriminante è sulla fattura (transaction PEC), non sulla config corrente,
        così funziona anche se la company è stata successivamente spostata su SDI standard.
        """
        self.ensure_one()
        if self._l10n_it_pec_is_pec_transaction():
            return self._l10n_it_pec_check_notifications()
        return super().action_check_l10n_it_edi()

    def _l10n_it_edi_update_send_state(self):
        """Override: esclude le fatture inviate via PEC dal polling proxy standard.
        Il cron standard chiama questo metodo con transaction ID del proxy;
        le fatture PEC hanno transaction ID diversi (Message-ID PEC) e vanno
        gestite tramite polling IMAP, non tramite il proxy.
        """
        pec_moves = self.filtered(lambda m: m._l10n_it_pec_is_pec_transaction())
        proxy_moves = self - pec_moves

        # Fatture PEC: polling IMAP per company
        for company in pec_moves.mapped('company_id'):
            try:
                handler = self.env['l10n_it_pec.mail.handler']
                handler._poll_company_pec(company)
            except Exception as e:
                _logger.warning(
                    "Errore polling PEC per company %s: %s", company.name, e
                )

        # Fatture standard: flusso proxy nativo
        if proxy_moves:
            super(AccountMove, proxy_moves)._l10n_it_edi_update_send_state()

    def _l10n_it_pec_check_notifications(self):
        """Controlla via IMAP se ci sono notifiche SDI per questa fattura."""
        self.ensure_one()
        company = self.company_id
        handler = self.env['l10n_it_pec.mail.handler']
        old_state = self.l10n_it_edi_state
        try:
            handler._poll_company_pec(company)
        except Exception as e:
            raise UserError(
                _("Errore durante il controllo PEC:\n%s") % str(e)
            )
        self.invalidate_recordset(fnames=['l10n_it_edi_state'])
        if self.l10n_it_edi_state != old_state:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Controllo PEC"),
                'message': _("Nessuna nuova notifica SDI trovata nella casella PEC."),
                'type': 'info',
                'sticky': False,
            },
        }

    def _l10n_it_edi_send(self, attachments_vals):
        """
        Override solo per la modalità PEC demo: simulazione senza cambio stato.
        Per PEC reale (test/production) e proxy standard → flusso Odoo nativo.
        """
        pec_demo = self.filtered(
            lambda m: m._l10n_it_edi_pec_is_active()
            and m.company_id.l10n_it_edi_pec_mode == 'demo'
        )
        rest = self - pec_demo

        results = {}

        # Tutto ciò che non è PEC demo → flusso standard
        # (per PEC reale, _l10n_it_edi_upload intercetta il trasporto)
        if rest:
            results.update(super(AccountMove, rest)._l10n_it_edi_send(
                {m: v for m, v in attachments_vals.items() if m in rest}
            ))

        # PEC demo: solo simulazione, nessun cambio stato EDI
        for move in pec_demo:
            attachment = attachments_vals.get(move, {})
            filename = attachment.get('name', '')
            xml_content = attachment.get('raw', b'')

            # Firma digitale PA: stessa logica di _l10n_it_edi_upload
            if move._l10n_it_pec_is_pa_invoice() and move.l10n_it_pec_signed_attachment_id:
                signed_att = move.l10n_it_pec_signed_attachment_id
                send_filename = signed_att.name
            elif move._l10n_it_pec_is_pa_invoice() and not move.l10n_it_pec_signed_attachment_id:
                error_message = _(
                    "Le fatture verso la PA richiedono la firma digitale. "
                    "Scaricare l'XML, firmarlo e ricaricare il file firmato."
                )
                move.l10n_it_edi_header = error_message
                move.sudo().message_post(body=error_message)
                results[filename] = {
                    'error_message': error_message,
                }
                continue
            else:
                send_filename = filename

            xml_bytes = xml_content if isinstance(xml_content, bytes) else xml_content
            att = move.env['ir.attachment'].create({
                'name': filename,
                'raw': xml_bytes,
                'res_model': 'account.move',
                'res_id': move.id,
                'mimetype': 'application/xml',
            })
            move.l10n_it_pec_xml_attachment_id = att
            move.l10n_it_pec_sent_date = fields.Datetime.now()
            move.l10n_it_pec_last_error = False

            message = _(
                "DEMO: simulazione invio fattura elettronica %s via PEC. "
                "Nessuna PEC è stata realmente inviata.", send_filename
            )
            move.sudo().message_post(body=message)
            results[filename] = {}

        return results

    def _l10n_it_edi_upload(self, files):
        """
        Override del trasporto EDI — Opzione C.

        Se la modalità PEC è attiva (test/production), invia via SMTP/PEC
        invece del proxy Odoo. Altrimenti, passa al flusso standard.

        Ritorna lo stesso formato dello standard:
        - Successo: {filename: {'id_transaction': '...'}}
        - Errore:   {filename: {'error': '...', 'error_description': '...'}}

        Il chiamante _l10n_it_edi_send() gestisce autonomamente:
        stato, transaction, header, messaggi chatter.
        """
        if not self._l10n_it_edi_pec_is_active():
            return super()._l10n_it_edi_upload(files)

        results = {}
        for file_data in (files or []):
            filename = file_data['filename']

            # Firma digitale PA: sostituisci contenuto con file firmato
            # Il filename originale è preservato come chiave nel dict dei risultati
            # perché il chiamante _l10n_it_edi_send() lo usa per il lookup.
            if self._l10n_it_pec_is_pa_invoice() and self.l10n_it_pec_signed_attachment_id:
                signed_att = self.l10n_it_pec_signed_attachment_id
                file_data = dict(file_data,
                    filename=signed_att.name,
                    xml=signed_att.datas,
                )
            elif self._l10n_it_pec_is_pa_invoice() and not self.l10n_it_pec_signed_attachment_id:
                results[filename] = {
                    'error': _("Firma digitale richiesta"),
                    'error_description': _(
                        "Le fatture verso la PA richiedono la firma digitale. "
                        "Scaricare l'XML, firmarlo e ricaricare il file firmato."
                    ),
                }
                continue

            try:
                self._l10n_it_pec_send_to_sdi(file_data)
                message_id = self.l10n_it_pec_message_id or 'pec_%s' % self.id
                results[filename] = {'id_transaction': message_id}
            except Exception as e:
                _logger.exception("Errore invio PEC fattura %s: %s", self.name, str(e))
                self.l10n_it_pec_last_error = str(e)
                results[filename] = {
                    'error': 'PEC_SEND',
                    'error_description': str(e),
                }
        return results

    # ══════════════════════════════════════════════════════════════════
    #  Generazione XML e invio PEC
    # ══════════════════════════════════════════════════════════════════
    
    def _l10n_it_pec_generate_xml(self):
        """
        Genera l'XML FatturaPA riutilizzando il motore standard di l10n_it_edi.
        Se l'attachment standard EDI esiste già, lo riusa per evitare duplicati.

        Usa _l10n_it_edi_render_xml() e _l10n_it_edi_generate_filename()
        definiti in l10n_it_edi/models/account_move.py.
        """
        self.ensure_one()

        # Riusa l'attachment standard EDI se già presente
        if self.l10n_it_edi_attachment_id:
            attachment = self.l10n_it_edi_attachment_id
            self.l10n_it_pec_xml_attachment_id = attachment
            return attachment.raw, attachment.name

        xml_content = self._l10n_it_edi_render_xml()
        filename = self._l10n_it_edi_generate_filename()

        # Salva come allegato
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'raw': xml_content,
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/xml',
        })
        self.l10n_it_pec_xml_attachment_id = attachment

        return xml_content, filename

    def _l10n_it_pec_send_to_sdi(self, file_data):
        """
        Invia la fattura allo SDI via PEC (test/production).
        La modalità demo è gestita in _l10n_it_edi_send() e non arriva qui.

        :param file_data: dict con 'filename' e 'xml' (base64) dal flusso standard.
        """
        self.ensure_one()
        company = self.company_id
        filename = file_data['filename']
        xml_bytes = b64decode(file_data['xml'])
        mode = company.l10n_it_edi_pec_mode

        # NON creare un attachment qui: l'XML è già disponibile in xml_bytes
        # dal parametro file_data. Lo standard creerà l10n_it_edi_attachment_id
        # dopo il ritorno di _l10n_it_edi_upload. Il campo l10n_it_pec_xml_attachment_id
        # verrà assegnato nel post-invio quando l10n_it_edi_attachment_id è disponibile.

        # ── INVIO REALE (test / production) ───────────────────────────
        company._check_pec_configuration()
        destination = company._get_pec_sdi_destination()

        # Costruzione email PEC
        msg = EmailMessage()
        msg['Subject'] = filename
        msg['From'] = company.l10n_it_pec_email or company.l10n_it_pec_smtp_user
        msg['To'] = destination
        msg.set_content(
            f"Invio fattura elettronica {self.name} — "
            f"Modalità: {mode}"
        )
        msg.add_attachment(
            xml_bytes,
            maintype='application',
            subtype='xml',
            filename=filename,
        )

        # Invio SMTP con gestione connessione sicura
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

        try:
            smtp.login(
                company.l10n_it_pec_smtp_user,
                company.l10n_it_pec_smtp_password,
            )
            smtp.send_message(msg)
        finally:
            try:
                smtp.quit()
            except Exception:
                pass

        # Aggiorna solo i campi PEC informativi.
        # Stato EDI, transaction, header, chatter → gestiti dallo standard.
        self.l10n_it_pec_sent_date = fields.Datetime.now()
        self.l10n_it_pec_message_id = msg.get('Message-ID', '')
        self.l10n_it_pec_last_error = False

    # ══════════════════════════════════════════════════════════════════
    #  Azione manuale: Invia via PEC (bottone nella vista fattura)
    # ══════════════════════════════════════════════════════════════════

    def action_l10n_it_pec_send(self):
        """Azione bottone: invia la fattura via PEC allo SDI tramite il flusso standard."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("La fattura deve essere confermata prima dell'invio."))
        if not self._l10n_it_edi_pec_is_active():
            raise UserError(
                _("La modalità PEC non è attiva. "
                  "Configurare in Impostazioni → Contabilità → PEC SDI.")
            )
        if self.l10n_it_edi_transaction:
            raise UserError(
                _("La fattura è già stata inviata allo SDI (transaction: %s). "
                  "Non è possibile inviarla di nuovo.", self.l10n_it_edi_transaction)
            )

        # Validazione dati XML (stessa logica dello standard action_l10n_it_edi_send)
        if errors := self._l10n_it_edi_export_data_check():
            messages = []
            for error_key, error_data in errors.items():
                messages.append(error_data['message'])
            self.l10n_it_edi_header = Markup('<br/>').join(messages)
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # Prepara attachment_vals SENZA consumare nuovo progressivo se c'è già un file firmato.
        # _l10n_it_edi_get_attachment_values internamente chiama _l10n_it_edi_generate_filename
        # che incrementa la sequenza: dobbiamo evitarlo quando è già stato firmato un file
        # con un progressivo già consumato.
        if self.l10n_it_pec_signed_attachment_id:
            # Ricava il nome base dal file firmato (rimuovi .p7m)
            signed_att = self.l10n_it_pec_signed_attachment_id
            base_name = signed_att.name
            if base_name.lower().endswith('.p7m'):
                base_name = base_name[:-4]
            # Genera XML al volo senza progressivo (verrà comunque sostituito dal p7m all'invio)
            xml_content = self._l10n_it_edi_render_xml()
            # Salva nel campo binario standard (Odoo crea l'ir.attachment automaticamente)
            self.l10n_it_edi_attachment_file = base64.b64encode(xml_content)
            # Rinomina l'attachment generato per usare il nome base del p7m
            self.invalidate_recordset(fnames=['l10n_it_edi_attachment_id', 'l10n_it_edi_attachment_file'])
            if self.l10n_it_edi_attachment_id:
                self.l10n_it_edi_attachment_id.name = base_name
            attachment_vals = {
                'name': base_name,
                'raw': xml_content,
                'res_model': 'account.move',
                'res_id': self.id,
                'mimetype': 'application/xml',
            }
        else:
            # Nessun file firmato: usa il flusso standard (consuma progressivo)
            attachment_vals = self._l10n_it_edi_get_attachment_values(pdf_values=None)
            self.env['ir.attachment'].create(attachment_vals)
            self.invalidate_recordset(fnames=['l10n_it_edi_attachment_id', 'l10n_it_edi_attachment_file'])
        self.message_post(attachment_ids=self.l10n_it_edi_attachment_id.ids)

        # Invio via flusso standard → _l10n_it_edi_upload → PEC
        self._l10n_it_edi_send({self: attachment_vals})
        self.is_move_sent = True
        # Punta l10n_it_pec_xml_attachment_id all'attachment standard (no duplicati)
        if self.l10n_it_edi_attachment_id:
            self.l10n_it_pec_xml_attachment_id = self.l10n_it_edi_attachment_id

    def action_l10n_it_pec_preview_xml(self):
        """Mostra l'XML della fattura nel browser senza scaricarlo."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("La fattura deve essere confermata per generare l'XML."))

        # Cerca attachment XML esistente
        attachment = self.l10n_it_edi_attachment_id
        if not attachment:
            attachment = self.l10n_it_pec_xml_attachment_id
        if not attachment:
            attachment = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'),
                ('res_id', '=', self.id),
                ('name', '=like', 'IT%.xml'),
            ], limit=1, order='create_date desc')

        if not attachment:
            # Genera l'XML al volo come attachment temporaneo (non legato alla fattura)
            # per non creare allegati visibili e non consumare il progressivo
            if errors := self._l10n_it_edi_export_data_check():
                messages = []
                for error_key, error_data in errors.items():
                    messages.append(error_data['message'])
                raise UserError('\n'.join(messages))
            xml_content = self._l10n_it_edi_render_xml()
            attachment = self.env['ir.attachment'].create({
                'name': 'anteprima_fattura.xml',
                'raw': xml_content,
                'mimetype': 'application/xml',
            })

        # Apre l'XML nel browser (senza download)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}',
            'target': 'new',
        }

    # ══════════════════════════════════════════════════════════════════
    #  Processamento notifiche SDI ricevute via PEC
    # ══════════════════════════════════════════════════════════════════

    def _l10n_it_pec_process_sdi_notification(self, notification_type, xml_content, raw_email=None):
        """
        Processa una notifica SDI ricevuta via PEC.
        Usa _l10n_it_edi_write_send_state() come lo standard Odoo per
        aggiornare stato, transaction e header in modo coerente.

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

        if not new_state:
            return

        # Salva notifica come allegato
        att_name = f"SDI_{notification_type}_{self.name.replace('/', '_')}.xml"
        self.env['ir.attachment'].create({
            'name': att_name,
            'raw': xml_content if isinstance(xml_content, bytes) else xml_content.encode('utf-8'),
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/xml',
        })

        filename = self.l10n_it_edi_attachment_id.name if self.l10n_it_edi_attachment_id else self.name
        message = _("Notifica SDI %(type)s (%(label)s) ricevuta per %(file)s.",
                     type=notification_type, label=label, file=filename)

        # Usa il metodo standard per aggiornare stato/transaction/header
        self._l10n_it_edi_write_send_state(
            transformed_notification={
                'l10n_it_edi_state': new_state,
                'l10n_it_edi_transaction': self.l10n_it_edi_transaction,
                'send_ack_to_edi_proxy': False,
                'date': fields.Date.today(),
                'filename': filename,
            },
            message=message,
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
                return 'accepted_by_pa_partner'
            elif 'EC02' in content:
                return 'rejected_by_pa_partner'
        except Exception:
            _logger.warning("Impossibile parsificare Notifica Esito per %s", self.name)

        return 'accepted_by_pa_partner'  # default safe: silenzio-assenso
