# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
import email
import imaplib
import logging
import re
from datetime import datetime, timedelta

from lxml import etree

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

NS_FPA = 'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2'
NS_TYPES = 'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fattura/messaggi/v1.0'

SDI_NOTIFICATION_MAP = {
    'RicevutaConsegna': 'ricevuta_consegna',
    'NotificaScarto': 'notifica_scarto',
    'NotificaMancataConsegna': 'notifica_mancata_consegna',
    'NotificaEsito': 'notifica_esito',
    'NotificaDecorrenzaTermini': 'notifica_decorrenza',
    'AttestazioneTrasmissioneFattura': 'attestazione_trasmissione',
}

SDI_NOTIFICATION_STATE_MAP = {
    'ricevuta_consegna': 'delivered',
    'notifica_scarto': 'rejected',
    'notifica_mancata_consegna': 'not_delivered',
    'notifica_esito': 'accepted',
    'notifica_decorrenza': 'accepted',
    'attestazione_trasmissione': 'delivered',
}


class PecMailHandler(models.AbstractModel):
    _name = 'l10n_it_edi.pec.mail.handler'
    _description = 'Gestore PEC per fatturazione elettronica SDI'

    @api.model
    def _cron_fetch_pec(self):
        """Cron job: scarica e processa email PEC dalla casella SDI."""
        companies = self.env['res.company'].search([
            ('l10n_it_edi_pec_mode', '=', 'production'),
            ('l10n_it_edi_pec_server_in_id', '!=', False),
            ('l10n_it_edi_pec_address', '!=', False),
        ])

        for company in companies:
            try:
                self._process_company_pec(company)
            except Exception as e:
                _logger.error(
                    "Errore elaborazione PEC per %s: %s",
                    company.name, str(e),
                )

    def _process_company_pec(self, company):
        """Processa la casella PEC di una singola azienda."""
        server = company.l10n_it_edi_pec_server_in_id
        imap = None

        try:
            # Connessione IMAP
            if server.server_type == 'imap':
                if server.is_ssl:
                    imap = imaplib.IMAP4_SSL(server.server, int(server.port))
                else:
                    imap = imaplib.IMAP4(server.server, int(server.port))

                imap.login(server.user, server.password)
                imap.select('INBOX')

                # Cerca email non lette
                status, messages = imap.search(None, 'UNSEEN')
                if status != 'OK' or not messages[0]:
                    return

                msg_ids = messages[0].split()
                _logger.info(
                    "PEC %s: %d nuovi messaggi da elaborare",
                    company.name, len(msg_ids),
                )

                for msg_id in msg_ids:
                    try:
                        self._process_single_pec(imap, msg_id, company)
                    except Exception as e:
                        _logger.error(
                            "Errore elaborazione messaggio PEC %s: %s",
                            msg_id, str(e),
                        )

                # Pulizia casella
                self._cleanup_pec(imap, company)

        except Exception as e:
            _logger.error("Errore connessione IMAP per %s: %s", company.name, e)
        finally:
            if imap:
                try:
                    imap.logout()
                except Exception:
                    pass

    def _process_single_pec(self, imap, msg_id, company):
        """Processa un singolo messaggio PEC."""
        status, msg_data = imap.fetch(msg_id, '(RFC822)')
        if status != 'OK':
            return

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        subject = msg.get('Subject', '')
        from_addr = msg.get('From', '')

        _logger.debug("PEC elaborazione: Subject=%s From=%s", subject, from_addr)

        # Cerca allegati XML
        xml_attachments = []
        for part in msg.walk():
            if part.get_content_type() in ('application/xml', 'text/xml'):
                xml_attachments.append({
                    'filename': part.get_filename() or 'unknown.xml',
                    'content': part.get_payload(decode=True),
                })
            elif part.get_filename() and part.get_filename().endswith('.p7m'):
                # File firmato .p7m — estrai contenuto XML
                p7m_content = part.get_payload(decode=True)
                xml_content = self._extract_xml_from_p7m(p7m_content)
                if xml_content:
                    xml_attachments.append({
                        'filename': part.get_filename().replace('.p7m', ''),
                        'content': xml_content,
                    })

        for xml_att in xml_attachments:
            self._process_xml_attachment(
                xml_att['filename'],
                xml_att['content'],
                company,
                raw_email=raw_email.decode('utf-8', errors='replace'),
            )

        # Marca come letta (sempre, indipendentemente dalla modalità pulizia)
        imap.store(msg_id, '+FLAGS', '\\Seen')

    def _process_xml_attachment(self, filename, xml_content, company, raw_email=None):
        """Processa un singolo allegato XML: notifica SDI o fattura passiva."""
        try:
            root = etree.fromstring(xml_content)
        except etree.XMLSyntaxError:
            _logger.warning("XML non valido: %s", filename)
            return

        root_tag = etree.QName(root.tag).localname if '}' in root.tag else root.tag

        # Identifica tipo di messaggio
        if root_tag in SDI_NOTIFICATION_MAP:
            self._process_sdi_notification(root, root_tag, filename, company, raw_email)
        elif root_tag == 'FatturaElettronica':
            self._process_passive_invoice(root, filename, xml_content, company, raw_email)
        else:
            _logger.info("XML ignorato (tipo sconosciuto): %s tag=%s", filename, root_tag)

    def _process_sdi_notification(self, root, root_tag, filename, company, raw_email):
        """Processa una notifica SDI e aggiorna lo stato della fattura."""
        transaction_type = SDI_NOTIFICATION_MAP.get(root_tag)
        new_state = SDI_NOTIFICATION_STATE_MAP.get(transaction_type)

        # Estrai identificativo SDI e nome file originale
        ns = {'n': NS_TYPES}
        sdi_id_el = root.find('.//n:IdentificativoSdI', ns)
        if sdi_id_el is None:
            sdi_id_el = root.find(f'.//{{{NS_TYPES}}}IdentificativoSdI')
        sdi_id = sdi_id_el.text if sdi_id_el is not None else None

        nome_file_el = root.find('.//n:NomeFile', ns)
        if nome_file_el is None:
            nome_file_el = root.find(f'.//{{{NS_TYPES}}}NomeFile')
        nome_file = nome_file_el.text if nome_file_el is not None else None

        # Cerca la fattura corrispondente
        move = None
        if nome_file:
            move = self.env['account.move'].search([
                ('l10n_it_edi_pec_sdi_filename', '=', nome_file),
                ('company_id', '=', company.id),
            ], limit=1)
        if not move and sdi_id:
            move = self.env['account.move'].search([
                ('l10n_it_edi_pec_sdi_id', '=', sdi_id),
                ('company_id', '=', company.id),
            ], limit=1)

        if not move:
            _logger.warning(
                "Notifica SDI %s: nessuna fattura trovata (file=%s, sdi_id=%s)",
                root_tag, nome_file, sdi_id,
            )
            return

        # Per notifica esito PA, controlla se è accettazione o rifiuto
        if root_tag == 'NotificaEsito':
            esito_el = root.find('.//n:Esito', ns)
            if esito_el is None:
                esito_el = root.find(f'.//{{{NS_TYPES}}}Esito')
            if esito_el is not None and esito_el.text == 'EC02':
                new_state = 'rejected'
                transaction_type = 'notifica_scarto'

        # Aggiorna fattura
        move.write({
            'l10n_it_edi_pec_state': new_state,
            'l10n_it_edi_pec_sdi_id': sdi_id or move.l10n_it_edi_pec_sdi_id,
        })

        # Estrai eventuale messaggio di errore
        error_msg = None
        if new_state == 'rejected':
            desc_el = root.find('.//n:Descrizione', ns)
            if desc_el is None:
                desc_el = root.find(f'.//{{{NS_TYPES}}}Descrizione')
            error_msg = desc_el.text if desc_el is not None else 'Scarto senza descrizione'
            move.l10n_it_edi_pec_last_error = error_msg

        # Crea transazione
        self.env['sdi.pec.transaction'].create({
            'move_id': move.id,
            'direction': 'out',
            'transaction_type': transaction_type,
            'state': new_state if new_state != 'not_delivered' else 'error',
            'sdi_id': sdi_id,
            'sdi_filename': nome_file,
            'error_message': error_msg,
            'raw_pec_content': raw_email[:5000] if raw_email else None,
        })

        # Log nel chatter
        state_labels = {
            'delivered': '✅ Consegnata',
            'accepted': '✅ Accettata dalla PA',
            'rejected': '❌ Scartata',
            'not_delivered': '⚠️ Mancata consegna',
        }
        move.message_post(
            body=_("%s — Notifica SDI: %s%s",
                   state_labels.get(new_state, new_state),
                   root_tag,
                   f"\n{error_msg}" if error_msg else ""),
            message_type='notification',
        )

    def _process_passive_invoice(self, root, filename, xml_content, company, raw_email):
        """Importa una fattura passiva ricevuta dallo SDI."""
        ns = {'p': NS_FPA}

        # Verifica che non sia già importata
        existing = self.env['sdi.pec.transaction'].search([
            ('sdi_filename', '=', filename),
            ('company_id', '=', company.id),
            ('direction', '=', 'in'),
        ], limit=1)
        if existing:
            _logger.info("Fattura passiva già importata: %s", filename)
            return

        # Estrai dati fornitore
        cedente = root.find(f'.//{{{NS_FPA}}}CedentePrestatore')
        if cedente is None:
            _logger.warning("CedentePrestatore non trovato in %s", filename)
            return

        # Cerca o crea partner
        partner = self._find_or_create_partner(cedente, company)

        # Crea fattura fornitore in bozza
        move_vals = {
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'company_id': company.id,
        }

        # Estrai data e numero documento
        dati_gen = root.find(f'.//{{{NS_FPA}}}DatiGeneraliDocumento')
        if dati_gen is not None:
            data_el = dati_gen.find(f'{{{NS_FPA}}}Data')
            if data_el is not None:
                move_vals['invoice_date'] = data_el.text
            numero_el = dati_gen.find(f'{{{NS_FPA}}}Numero')
            if numero_el is not None:
                move_vals['ref'] = numero_el.text

        move = self.env['account.move'].with_company(company).create(move_vals)
        move.l10n_it_edi_pec_state = 'delivered'

        # Salva XML come allegato
        self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(xml_content),
            'res_model': 'account.move',
            'res_id': move.id,
            'mimetype': 'application/xml',
        })

        # Crea transazione
        self.env['sdi.pec.transaction'].create({
            'move_id': move.id,
            'direction': 'in',
            'transaction_type': 'receive_invoice',
            'state': 'delivered',
            'sdi_filename': filename,
            'xml_content': base64.b64encode(xml_content),
            'raw_pec_content': raw_email[:5000] if raw_email else None,
        })

        move.message_post(
            body=_("📥 Fattura passiva ricevuta da SDI: %s\n"
                   "Fornitore: %s\nRivedere e confermare manualmente.",
                   filename, partner.name),
            message_type='notification',
        )

        _logger.info("Fattura passiva importata: %s → %s", filename, move.name)

    def _find_or_create_partner(self, cedente_node, company):
        """Cerca partner per P.IVA/CF o lo crea dall'XML."""
        ns_fpa = NS_FPA
        dati_anag = cedente_node.find(f'.//{{{ns_fpa}}}DatiAnagrafici')
        if dati_anag is None:
            return self.env['res.partner'].create({
                'name': 'Fornitore sconosciuto (da SDI)',
                'company_id': company.id,
            })

        # P.IVA
        id_fiscale = dati_anag.find(f'{{{ns_fpa}}}IdFiscaleIVA')
        vat = None
        if id_fiscale is not None:
            paese = id_fiscale.find(f'{{{ns_fpa}}}IdPaese')
            codice = id_fiscale.find(f'{{{ns_fpa}}}IdCodice')
            if paese is not None and codice is not None:
                vat = f"{paese.text}{codice.text}"

        # Codice Fiscale
        cf_el = dati_anag.find(f'{{{ns_fpa}}}CodiceFiscale')
        cf = cf_el.text if cf_el is not None else None

        # Cerca per P.IVA
        if vat:
            partner = self.env['res.partner'].search([
                ('vat', '=', vat),
            ], limit=1)
            if partner:
                return partner

        # Cerca per CF
        if cf:
            partner = self.env['res.partner'].search([
                ('l10n_it_codice_fiscale', '=', cf),
            ], limit=1)
            if partner:
                return partner

        # Crea nuovo partner
        denominazione = dati_anag.find(f'.//{{{ns_fpa}}}Denominazione')
        nome = dati_anag.find(f'.//{{{ns_fpa}}}Nome')
        cognome = dati_anag.find(f'.//{{{ns_fpa}}}Cognome')

        partner_name = 'Fornitore da SDI'
        if denominazione is not None:
            partner_name = denominazione.text
        elif nome is not None and cognome is not None:
            partner_name = f"{cognome.text} {nome.text}"

        vals = {
            'name': partner_name,
            'company_type': 'company',
            'supplier_rank': 1,
            'company_id': company.id,
        }
        if vat:
            vals['vat'] = vat
        if cf:
            vals['l10n_it_codice_fiscale'] = cf

        # Indirizzo
        sede = cedente_node.find(f'.//{{{ns_fpa}}}Sede')
        if sede is not None:
            indirizzo = sede.find(f'{{{ns_fpa}}}Indirizzo')
            cap = sede.find(f'{{{ns_fpa}}}CAP')
            comune = sede.find(f'{{{ns_fpa}}}Comune')
            provincia = sede.find(f'{{{ns_fpa}}}Provincia')

            if indirizzo is not None:
                vals['street'] = indirizzo.text
            if cap is not None:
                vals['zip'] = cap.text
            if comune is not None:
                vals['city'] = comune.text
            if provincia is not None:
                state = self.env['res.country.state'].search([
                    ('code', '=', provincia.text),
                    ('country_id.code', '=', 'IT'),
                ], limit=1)
                if state:
                    vals['state_id'] = state.id

            vals['country_id'] = self.env.ref('base.it').id

        return self.env['res.partner'].create(vals)

    def _extract_xml_from_p7m(self, p7m_content):
        """Estrae il contenuto XML da un file firmato .p7m (CAdES)."""
        try:
            # Il contenuto XML è embedddato nel PKCS#7 — cercalo con pattern
            xml_start = p7m_content.find(b'<?xml')
            if xml_start == -1:
                xml_start = p7m_content.find(b'<p:FatturaElettronica')
            if xml_start == -1:
                xml_start = p7m_content.find(b'<FatturaElettronica')

            if xml_start >= 0:
                # Cerca la fine dell'XML
                xml_end_markers = [
                    b'</p:FatturaElettronica>',
                    b'</FatturaElettronica>',
                    b'</ns0:FatturaElettronica>',
                ]
                for marker in xml_end_markers:
                    xml_end = p7m_content.find(marker, xml_start)
                    if xml_end >= 0:
                        return p7m_content[xml_start:xml_end + len(marker)]

            _logger.warning("Impossibile estrarre XML da .p7m")
            return None
        except Exception as e:
            _logger.error("Errore estrazione .p7m: %s", e)
            return None

    def _cleanup_pec(self, imap, company):
        """Pulizia casella PEC in base alla configurazione."""
        mode = company.l10n_it_edi_pec_cleanup_mode
        if mode == 'keep':
            return

        days = company.l10n_it_edi_pec_cleanup_days if mode == 'delete_delay' else 0

        try:
            if mode == 'delete_now':
                # Elimina tutte le email lette
                status, messages = imap.search(None, 'SEEN')
                if status == 'OK' and messages[0]:
                    for msg_id in messages[0].split():
                        imap.store(msg_id, '+FLAGS', '\\Deleted')
                    imap.expunge()

            elif mode == 'delete_delay' and days > 0:
                # Elimina email lette più vecchie di N giorni
                cutoff = (datetime.now() - timedelta(days=days)).strftime('%d-%b-%Y')
                status, messages = imap.search(None, f'SEEN BEFORE {cutoff}')
                if status == 'OK' and messages[0]:
                    msg_id_list = messages[0].split()
                    for msg_id in msg_id_list:
                        imap.store(msg_id, '+FLAGS', '\\Deleted')
                    imap.expunge()
                    _logger.info(
                        "PEC %s: eliminati %d messaggi più vecchi di %d giorni",
                        company.name, len(msg_id_list), days,
                    )

        except Exception as e:
            _logger.error("Errore pulizia PEC: %s", e)
