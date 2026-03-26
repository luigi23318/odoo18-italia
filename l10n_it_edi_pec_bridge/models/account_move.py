# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from datetime import datetime

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Namespace XML FatturaPA
NS_FPA = 'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2'
NS_TYPES = 'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fattura/messaggi/v1.0'

# Mapping notifiche SDI → stato fattura
SDI_NOTIFICATION_STATE_MAP = {
    'ricevuta_consegna': 'delivered',
    'notifica_scarto': 'rejected',
    'notifica_mancata_consegna': 'not_delivered',
    'notifica_esito': 'accepted',
    'notifica_decorrenza': 'accepted',
    'attestazione_trasmissione': 'delivered',
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ── Campi SDI PEC ───────────────────────────────────────────────────
    l10n_it_edi_pec_state = fields.Selection(
        selection=[
            ('to_send', 'Da inviare'),
            ('sent', 'Inviata a SDI'),
            ('delivered', 'Consegnata'),
            ('accepted', 'Accettata'),
            ('rejected', 'Scartata'),
            ('not_delivered', 'Mancata consegna'),
            ('demo', 'Demo'),
            ('validated', 'Validata'),
        ],
        string='Stato SDI PEC',
        copy=False,
        tracking=True,
        help="Stato della trasmissione della fattura allo SDI via PEC.",
    )
    l10n_it_edi_pec_transaction_ids = fields.One2many(
        'sdi.pec.transaction',
        'move_id',
        string='Transazioni SDI PEC',
    )
    l10n_it_edi_pec_last_error = fields.Text(
        string='Ultimo errore SDI',
        copy=False,
    )
    l10n_it_edi_pec_sdi_filename = fields.Char(
        string='Nome file SDI',
        copy=False,
        help="Nome file XML inviato allo SDI (es. IT01234567890_00042.xml)",
    )
    l10n_it_edi_pec_sdi_id = fields.Char(
        string='Identificativo SDI',
        copy=False,
    )
    l10n_it_edi_pec_message_id = fields.Char(
        string='Message-ID PEC',
        copy=False,
    )

    # ── Computed: visibilità bottoni ─────────────────────────────────────
    l10n_it_edi_pec_show_send = fields.Boolean(compute='_compute_pec_button_visibility')
    l10n_it_edi_pec_show_demo = fields.Boolean(compute='_compute_pec_button_visibility')
    l10n_it_edi_pec_show_validate = fields.Boolean(compute='_compute_pec_button_visibility')
    l10n_it_edi_pec_show_download = fields.Boolean(compute='_compute_pec_button_visibility')
    l10n_it_edi_pec_show_retry = fields.Boolean(compute='_compute_pec_button_visibility')

    @api.depends('state', 'move_type', 'country_code', 'l10n_it_edi_pec_state')
    def _compute_pec_button_visibility(self):
        for move in self:
            is_it_out = (
                move.country_code == 'IT'
                and move.move_type in ('out_invoice', 'out_refund')
                and move.state == 'posted'
            )
            mode = move.company_id.l10n_it_edi_pec_mode
            pec_state = move.l10n_it_edi_pec_state

            move.l10n_it_edi_pec_show_send = (
                is_it_out and mode == 'production'
                and pec_state in (False, 'to_send')
            )
            move.l10n_it_edi_pec_show_demo = (
                is_it_out and mode == 'demo'
                and pec_state in (False, 'to_send', 'demo')
            )
            move.l10n_it_edi_pec_show_validate = (
                is_it_out and mode == 'validation'
                and pec_state in (False, 'to_send', 'validated')
            )
            move.l10n_it_edi_pec_show_download = (
                is_it_out and pec_state in ('validated', 'demo')
            )
            move.l10n_it_edi_pec_show_retry = (
                is_it_out and mode == 'production'
                and pec_state == 'rejected'
            )

    # ════════════════════════════════════════════════════════════════════
    #  OVERRIDE CONFERMA FATTURA
    # ════════════════════════════════════════════════════════════════════

    def _post(self, soft=True):
        """Dopo la conferma, imposta stato SDI a 'Da inviare' per fatture italiane."""
        posted = super()._post(soft=soft)
        for move in posted:
            if (
                move.country_code == 'IT'
                and move.move_type in ('out_invoice', 'out_refund')
                and move.company_id.l10n_it_edi_pec_mode == 'production'
                and not move.l10n_it_edi_pec_state
            ):
                move.l10n_it_edi_pec_state = 'to_send'
        return posted

    # ════════════════════════════════════════════════════════════════════
    #  AZIONI UTENTE
    # ════════════════════════════════════════════════════════════════════

    def action_l10n_it_edi_pec_send(self):
        """Invia la fattura a SDI via PEC (modalità produzione)."""
        self.ensure_one()
        self._check_pec_config()

        company = self.company_id
        xml_content = self._get_or_generate_xml()
        filename = self._generate_sdi_filename()

        # Costruisci email PEC
        msg = EmailMessage()
        msg['From'] = company.l10n_it_edi_pec_address
        msg['To'] = company.l10n_it_edi_pec_sdi_address
        msg['Subject'] = filename
        msg_id = make_msgid(domain=company.l10n_it_edi_pec_address.split('@')[1])
        msg['Message-ID'] = msg_id
        msg.set_content('Fattura elettronica in allegato.')
        msg.add_attachment(
            xml_content,
            maintype='application',
            subtype='xml',
            filename=filename,
        )

        # Invio via SMTP
        try:
            smtp_server = company.l10n_it_edi_pec_server_out_id
            with smtp_server.connect() as smtp:
                smtp.send_message(msg)
        except Exception as e:
            self.l10n_it_edi_pec_last_error = str(e)
            self.message_post(
                body=_("❌ Errore invio PEC a SDI: %s", str(e)),
                message_type='notification',
            )
            raise UserError(_("Errore durante l'invio PEC: %s") % str(e))

        # Aggiorna stato
        self.write({
            'l10n_it_edi_pec_state': 'sent',
            'l10n_it_edi_pec_sdi_filename': filename,
            'l10n_it_edi_pec_message_id': msg_id,
            'l10n_it_edi_pec_last_error': False,
        })

        # Crea transazione
        self.env['sdi.pec.transaction'].create({
            'move_id': self.id,
            'direction': 'out',
            'transaction_type': 'send',
            'state': 'sent',
            'sdi_filename': filename,
            'sdi_message_id': msg_id,
            'xml_content': base64.b64encode(xml_content),
        })

        self.message_post(
            body=_("✅ Fattura inviata a SDI via PEC: %s", filename),
            message_type='notification',
        )

    def action_l10n_it_edi_pec_demo(self):
        """Simula invio a SDI senza inviare PEC (modalità demo)."""
        self.ensure_one()
        filename = 'DEMO_' + self._generate_sdi_filename()

        xml_content = self._get_or_generate_xml()

        self.write({
            'l10n_it_edi_pec_state': 'demo',
            'l10n_it_edi_pec_sdi_filename': filename,
            'l10n_it_edi_pec_last_error': False,
        })

        # Salva XML come allegato
        self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(xml_content),
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/xml',
        })

        self.env['sdi.pec.transaction'].create({
            'move_id': self.id,
            'direction': 'out',
            'transaction_type': 'demo_simulation',
            'state': 'demo',
            'sdi_filename': filename,
            'xml_content': base64.b64encode(xml_content),
        })

        self.message_post(
            body=_("🧪 Simulazione demo invio SDI: %s (nessuna PEC inviata)", filename),
            message_type='notification',
        )

    def action_l10n_it_edi_pec_validate(self):
        """Valida XML senza invio (modalità validazione)."""
        self.ensure_one()
        filename = 'VALIDAZIONE_' + self._generate_sdi_filename()
        xml_content = self._get_or_generate_xml()

        # Validazione formale dell'XML
        errors = self._validate_xml_content(xml_content)
        if errors:
            self.l10n_it_edi_pec_last_error = '\n'.join(errors)
            self.message_post(
                body=_("⚠️ Validazione XML fallita:\n%s", '\n'.join(errors)),
                message_type='notification',
            )
            raise UserError(_("Errori di validazione:\n%s") % '\n'.join(errors))

        self.write({
            'l10n_it_edi_pec_state': 'validated',
            'l10n_it_edi_pec_sdi_filename': filename,
            'l10n_it_edi_pec_last_error': False,
        })

        self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(xml_content),
            'res_model': 'account.move',
            'res_id': self.id,
            'mimetype': 'application/xml',
        })

        self.message_post(
            body=_("✅ XML validato con successo: %s\n"
                   "Scaricalo per verifica sul portale Fatture e Corrispettivi dell'AdE.",
                   filename),
            message_type='notification',
        )

    def action_l10n_it_edi_pec_download_xml(self):
        """Scarica l'XML per verifica manuale su portale AdE."""
        self.ensure_one()
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
            ('name', '=', self.l10n_it_edi_pec_sdi_filename),
        ], limit=1)
        if not attachment:
            raise UserError(_("XML non trovato. Eseguire prima la validazione o la simulazione demo."))

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_l10n_it_edi_pec_retry(self):
        """Reinvia fattura scartata a SDI dopo correzione."""
        self.ensure_one()
        self.l10n_it_edi_pec_state = 'to_send'
        self.l10n_it_edi_pec_last_error = False
        self.message_post(
            body=_("🔄 Stato resettato a 'Da inviare' per reinvio a SDI."),
            message_type='notification',
        )

    def action_l10n_it_edi_pec_reset_demo(self):
        """Resetta fatture demo a 'Da inviare'."""
        for move in self:
            if move.l10n_it_edi_pec_state == 'demo':
                move.l10n_it_edi_pec_state = 'to_send'
                move.l10n_it_edi_pec_sdi_filename = False

    def action_l10n_it_edi_pec_delete_demo(self):
        """Cancella fatture in stato demo (solo bozze non contabilizzate)."""
        for move in self:
            if move.l10n_it_edi_pec_state == 'demo' and move.state == 'draft':
                move.unlink()

    # ════════════════════════════════════════════════════════════════════
    #  METODI INTERNI
    # ════════════════════════════════════════════════════════════════════

    def _check_pec_config(self):
        """Verifica che la configurazione PEC sia completa."""
        company = self.company_id
        errors = []
        if not company.l10n_it_edi_pec_server_out_id:
            errors.append(_("Server PEC in uscita (SMTP) non configurato"))
        if not company.l10n_it_edi_pec_address:
            errors.append(_("Indirizzo PEC dedicato SDI non configurato"))
        if not company.l10n_it_edi_pec_sdi_address:
            errors.append(_("Indirizzo PEC SDI non configurato"))
        if errors:
            raise UserError(_(
                "Configurazione PEC SDI incompleta:\n%s\n\n"
                "Vai in Contabilità → Configurazione → Impostazioni → Fatturazione Elettronica PEC",
                '\n'.join(f"• {e}" for e in errors),
            ))

    def _get_or_generate_xml(self):
        """Recupera l'XML già generato da l10n_it_edi o lo genera.

        In Odoo 18, l10n_it_edi genera l'XML tramite il metodo
        _l10n_it_edi_render_xml() e lo salva nel campo
        l10n_it_edi_attachment_file (accessibile via l10n_it_edi_attachment_id).
        """
        self.ensure_one()

        # 1. Cerca l'allegato ufficiale generato da l10n_it_edi (Odoo 18)
        if hasattr(self, 'l10n_it_edi_attachment_id') and self.l10n_it_edi_attachment_id:
            return self.l10n_it_edi_attachment_id.raw

        # 2. Se non esiste, genera l'XML tramite l10n_it_edi
        if hasattr(self, '_l10n_it_edi_render_xml'):
            # Verifica prerequisiti
            if hasattr(self, '_l10n_it_edi_ready_for_xml_export') and not self._l10n_it_edi_ready_for_xml_export():
                raise UserError(_("La fattura non è pronta per l'esportazione XML. "
                                  "Verifica che sia confermata e che i dati siano completi."))
            # Controlla errori di validazione
            # _l10n_it_edi_export_data_check() ritorna un dict dove ogni valore
            # è un dict con chiavi: 'message', 'action_text' (opz.), 'action' (opz.)
            if hasattr(self, '_l10n_it_edi_export_data_check'):
                errors = self._l10n_it_edi_export_data_check()
                if errors:
                    error_msgs = [
                        err_data.get('message', str(err_data))
                        for err_data in errors.values()
                        if isinstance(err_data, dict)
                    ]
                    if error_msgs:
                        raise UserError(_("Errori nella generazione XML FatturaPA:\n%s") %
                                        '\n'.join(f"• {e}" for e in error_msgs))

            xml_content = self._l10n_it_edi_render_xml()

            # Salva l'allegato tramite il meccanismo standard di l10n_it_edi
            attachment_vals = self._l10n_it_edi_get_attachment_values()
            self.env['ir.attachment'].create(attachment_vals)
            self.invalidate_recordset(fnames=['l10n_it_edi_attachment_id'])

            return xml_content

        raise UserError(_("Impossibile generare l'XML FatturaPA. "
                          "Verifica che il modulo l10n_it_edi sia installato e configurato."))

    def _generate_sdi_filename(self):
        """Genera il nome file conforme SDI.

        Usa il metodo ufficiale di l10n_it_edi (Odoo 18) se disponibile,
        altrimenti genera un nome in formato IT{PIVA}_{progressivo}.xml.
        """
        self.ensure_one()
        # Usa il filename ufficiale di l10n_it_edi se già generato
        if hasattr(self, 'l10n_it_edi_attachment_id') and self.l10n_it_edi_attachment_id:
            return self.l10n_it_edi_attachment_id.name

        # Usa il generatore di filename di l10n_it_edi (sequenza base-62)
        if hasattr(self, '_l10n_it_edi_generate_filename'):
            return self._l10n_it_edi_generate_filename()

        # Fallback manuale
        company = self.company_id
        vat = company.vat
        if vat and vat.startswith('IT'):
            vat = vat[2:]
        elif not vat:
            vat = company.l10n_it_codice_fiscale or '00000000000'

        count = self.env['sdi.pec.transaction'].search_count([
            ('company_id', '=', company.id),
            ('direction', '=', 'out'),
            ('transaction_type', '=', 'send'),
        ])
        progressive = format(count + 1, '05d')

        return f"IT{vat}_{progressive}.xml"

    def _validate_xml_content(self, xml_content):
        """Validazione formale dell'XML FatturaPA."""
        errors = []
        try:
            root = etree.fromstring(xml_content)
        except etree.XMLSyntaxError as e:
            return [_("XML malformato: %s") % str(e)]

        # Controlla namespace
        if NS_FPA not in root.nsmap.values() and NS_FPA not in (root.tag or ''):
            errors.append(_("Namespace FatturaPA non trovato nell'XML"))

        # Controlla campi obbligatori base
        ns = {'p': NS_FPA}
        checks = [
            ('.//p:DatiTrasmissione', 'DatiTrasmissione'),
            ('.//p:CedentePrestatore', 'CedentePrestatore'),
            ('.//p:CessionarioCommittente', 'CessionarioCommittente'),
            ('.//p:DatiGeneraliDocumento', 'DatiGeneraliDocumento'),
        ]
        for xpath, name in checks:
            if root.find(xpath, ns) is None:
                # Prova senza namespace (alcuni generatori non usano prefisso)
                if root.find(f'.//{{{NS_FPA}}}{name}') is None:
                    errors.append(_("Sezione obbligatoria mancante: %s") % name)

        return errors
