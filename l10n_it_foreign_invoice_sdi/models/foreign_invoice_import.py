import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Tipo documento per fatture estere passive
TD_SELECTION = [
    ('TD17', 'TD17 - Integrazione/autofattura per acquisto servizi dall\'estero'),
    ('TD18', 'TD18 - Integrazione per acquisto di beni intracomunitari'),
    ('TD19', 'TD19 - Integrazione/autofattura per acquisto di beni art.17 c.2 DPR 633/72'),
]

SDI_STATE_SELECTION = [
    ('draft', 'Bozza'),
    ('extracted', 'Dati Estratti'),
    ('reviewed', 'Revisionato'),
    ('xml_generated', 'XML Generato'),
    ('xml_validated', 'XML Validato'),
    ('sent', 'Inviato SDI'),
    ('delivered', 'Consegnato'),
    ('accepted', 'Accettato'),
    ('rejected', 'Scartato'),
    ('error', 'Errore'),
]


class ForeignInvoiceImport(models.Model):
    _name = 'foreign.invoice.import'
    _description = 'Importazione Fattura Estera Passiva'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # === Identificazione ===
    name = fields.Char(
        string='Riferimento',
        required=True,
        readonly=True,
        default='/',
        copy=False,
        tracking=True,
    )
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Azienda',
        required=True,
        default=lambda self: self.env.company,
    )
    batch_id = fields.Many2one(
        'foreign.invoice.batch',
        string='Batch',
        ondelete='set null',
        index=True,
    )

    # === Stato ===
    state = fields.Selection(
        selection=SDI_STATE_SELECTION,
        string='Stato',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )

    # === Tipo documento ===
    document_type = fields.Selection(
        selection=TD_SELECTION,
        string='Tipo Documento',
        required=True,
        tracking=True,
        help='TD17: Servizi esteri, TD18: Beni intraUE, TD19: Beni art.17 c.2',
    )

    # === PDF Originale ===
    pdf_file = fields.Binary(
        string='PDF Fattura Estera',
        attachment=True,
    )
    pdf_filename = fields.Char(
        string='Nome File PDF',
    )

    # === Dati Cedente/Prestatore (Fornitore Estero) ===
    supplier_partner_id = fields.Many2one(
        'res.partner',
        string='Fornitore',
        tracking=True,
    )
    supplier_denomination = fields.Char(
        string='Denominazione Fornitore',
        tracking=True,
    )
    supplier_vat = fields.Char(
        string='Partita IVA Estera',
        tracking=True,
    )
    supplier_tax_code = fields.Char(
        string='Codice Fiscale Fornitore',
    )
    supplier_country_id = fields.Many2one(
        'res.country',
        string='Paese Fornitore',
        tracking=True,
    )
    supplier_address_street = fields.Char(
        string='Indirizzo Fornitore',
    )
    supplier_address_zip = fields.Char(
        string='CAP Fornitore',
    )
    supplier_address_city = fields.Char(
        string='Città Fornitore',
    )
    supplier_address_province = fields.Char(
        string='Provincia Fornitore',
        size=2,
    )

    # === Dati Cessionario/Committente (Azienda Italiana) ===
    buyer_vat = fields.Char(
        string='P.IVA Cessionario',
        related='company_id.vat',
        readonly=True,
    )
    buyer_tax_code = fields.Char(
        string='Codice Fiscale Cessionario',
        related='company_id.l10n_it_codice_fiscale',
        readonly=True,
    )

    # === Dati Fattura ===
    invoice_number = fields.Char(
        string='Numero Fattura Estera',
        tracking=True,
    )
    invoice_date = fields.Date(
        string='Data Fattura Estera',
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Valuta',
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )

    # === Righe fattura ===
    line_ids = fields.One2many(
        'foreign.invoice.import.line',
        'import_id',
        string='Righe Fattura',
    )

    # === Totali ===
    total_untaxed = fields.Monetary(
        string='Totale Imponibile',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_tax = fields.Monetary(
        string='Totale Imposta',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_amount = fields.Monetary(
        string='Totale Documento',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )

    # === Motore di estrazione ===
    extraction_engine = fields.Selection(
        selection=[
            ('tesseract', 'Tesseract OCR (Locale)'),
            ('acube', 'A-Cube API (Cloud)'),
        ],
        string='Motore Estrazione',
    )
    extraction_date = fields.Datetime(
        string='Data Estrazione',
        readonly=True,
    )
    extraction_confidence = fields.Float(
        string='Confidenza Estrazione (%)',
        readonly=True,
    )

    # === Revisione operatore ===
    reviewed = fields.Boolean(
        string='Revisionato',
        default=False,
        tracking=True,
    )
    reviewer_id = fields.Many2one(
        'res.users',
        string='Revisionato da',
        readonly=True,
    )
    review_date = fields.Datetime(
        string='Data Revisione',
        readonly=True,
    )
    review_notes = fields.Text(
        string='Note Revisione',
    )

    # === XML FatturaPA ===
    xml_file = fields.Binary(
        string='XML FatturaPA',
        attachment=True,
        readonly=True,
    )
    xml_filename = fields.Char(
        string='Nome File XML',
        readonly=True,
    )
    xml_generation_date = fields.Datetime(
        string='Data Generazione XML',
        readonly=True,
    )
    xml_validation_errors = fields.Text(
        string='Errori Validazione XSD',
        readonly=True,
    )

    # === Progressivo invio ===
    progressive_number = fields.Char(
        string='Progressivo Invio',
        readonly=True,
        copy=False,
    )

    # === SDI / Aruba ===
    sdi_file_id = fields.Char(
        string='ID File SDI',
        readonly=True,
        copy=False,
        tracking=True,
    )
    sdi_notification_ids = fields.One2many(
        'foreign.invoice.sdi.notification',
        'import_id',
        string='Notifiche SDI',
        readonly=True,
    )
    sdi_send_date = fields.Datetime(
        string='Data Invio SDI',
        readonly=True,
    )
    sdi_delivery_date = fields.Datetime(
        string='Data Consegna SDI',
        readonly=True,
    )
    sdi_error_message = fields.Text(
        string='Messaggio Errore SDI',
        readonly=True,
    )

    # === Contabilizzazione ===
    account_move_id = fields.Many2one(
        'account.move',
        string='Registrazione Contabile',
        readonly=True,
        copy=False,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Registro',
    )

    # === Campi tecnici ===
    can_send = fields.Boolean(
        compute='_compute_can_send',
    )

    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------

    @api.depends('name', 'invoice_number', 'supplier_denomination')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.name or '']
            if rec.supplier_denomination:
                parts.append(rec.supplier_denomination)
            if rec.invoice_number:
                parts.append(rec.invoice_number)
            rec.display_name = ' - '.join(parts)

    @api.depends('line_ids.price_subtotal', 'line_ids.tax_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_untaxed = sum(rec.line_ids.mapped('price_subtotal'))
            rec.total_tax = sum(rec.line_ids.mapped('tax_amount'))
            rec.total_amount = rec.total_untaxed + rec.total_tax

    @api.depends('state')
    def _compute_can_send(self):
        for rec in self:
            rec.can_send = rec.state == 'xml_validated'

    # -------------------------------------------------------------------------
    # CONSTRAINS
    # -------------------------------------------------------------------------

    @api.constrains('supplier_vat', 'supplier_country_id')
    def _check_supplier_vat(self):
        for rec in self:
            if rec.supplier_country_id and rec.supplier_country_id.code == 'IT':
                raise ValidationError(
                    _('Il fornitore non può essere italiano per una fattura estera.')
                )

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'foreign.invoice.import'
                ) or '/'
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # AZIONI
    # -------------------------------------------------------------------------

    def action_extract(self):
        """Avvia estrazione dati dal PDF."""
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_('Nessun PDF caricato.'))
        engine = self.extraction_engine or self.env['ir.config_parameter'].sudo().get_param(
            'l10n_it_foreign_invoice_sdi.default_extraction_engine', 'tesseract'
        )
        self.extraction_engine = engine
        service = self.env['foreign.invoice.extraction.service']
        service.extract(self, engine)
        self.write({
            'state': 'extracted',
            'extraction_date': fields.Datetime.now(),
        })
        return True

    def action_mark_reviewed(self):
        """Operatore conferma la revisione dei dati estratti."""
        self.ensure_one()
        if self.state not in ('extracted', 'draft'):
            raise UserError(_('Puoi revisionare solo fatture in stato Estratto o Bozza.'))
        self.write({
            'state': 'reviewed',
            'reviewed': True,
            'reviewer_id': self.env.uid,
            'review_date': fields.Datetime.now(),
        })
        return True

    def action_generate_xml(self):
        """Genera XML FatturaPA v1.2.3."""
        self.ensure_one()
        if self.state != 'reviewed':
            raise UserError(_('La fattura deve essere revisionata prima di generare l\'XML.'))
        generator = self.env['fatturapa.xml.generator']
        xml_content, filename = generator.generate(self)
        self.write({
            'xml_file': base64.b64encode(xml_content),
            'xml_filename': filename,
            'xml_generation_date': fields.Datetime.now(),
            'state': 'xml_generated',
        })
        return True

    def action_validate_xml(self):
        """Valida XML contro schema XSD."""
        self.ensure_one()
        if self.state != 'xml_generated':
            raise UserError(_('Genera prima l\'XML.'))
        generator = self.env['fatturapa.xml.generator']
        errors = generator.validate_xsd(self)
        if errors:
            self.write({
                'xml_validation_errors': '\n'.join(errors),
                'state': 'error',
            })
            raise UserError(_('Errori di validazione XSD:\n%s') % '\n'.join(errors))
        self.write({
            'xml_validation_errors': False,
            'state': 'xml_validated',
        })
        return True

    def action_send_sdi(self):
        """Invia XML al SDI tramite Aruba."""
        self.ensure_one()
        if self.state != 'xml_validated':
            raise UserError(_('L\'XML deve essere validato prima dell\'invio.'))
        aruba = self.env['aruba.sdi.service']
        result = aruba.send_invoice(self)
        self.write({
            'sdi_file_id': result.get('file_id'),
            'sdi_send_date': fields.Datetime.now(),
            'state': 'sent',
        })
        return True

    def action_check_sdi_status(self):
        """Controlla stato notifiche SDI."""
        self.ensure_one()
        if not self.sdi_file_id:
            raise UserError(_('Nessun invio SDI registrato.'))
        aruba = self.env['aruba.sdi.service']
        aruba.check_notification(self)
        return True

    def action_reset_to_draft(self):
        """Riporta in bozza."""
        self.ensure_one()
        if self.state in ('sent', 'delivered', 'accepted'):
            raise UserError(_('Non puoi riportare in bozza una fattura già inviata al SDI.'))
        self.write({'state': 'draft'})
        return True

    def action_download_xml(self):
        """Download singolo XML."""
        self.ensure_one()
        if not self.xml_file:
            raise UserError(_('Nessun XML generato.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=foreign.invoice.import&id=%d'
                   '&field=xml_file&filename_field=xml_filename&download=true' % self.id,
            'target': 'self',
        }

    def action_view_account_move(self):
        """Apri la registrazione contabile collegata."""
        self.ensure_one()
        if not self.account_move_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.account_move_id.id,
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_create_account_move(self):
        """Crea registrazione contabile con reverse charge."""
        self.ensure_one()
        if self.account_move_id:
            raise UserError(_('Registrazione contabile già presente.'))
        if self.state not in ('sent', 'delivered', 'accepted'):
            raise UserError(_('La fattura deve essere almeno inviata al SDI.'))

        move_vals = {
            'move_type': 'in_invoice',
            'partner_id': self.supplier_partner_id.id,
            'invoice_date': self.invoice_date,
            'journal_id': self.journal_id.id if self.journal_id else False,
            'ref': self.invoice_number,
            'currency_id': self.currency_id.id,
            'invoice_line_ids': [
                fields.Command.create({
                    'name': line.description or '/',
                    'quantity': line.quantity,
                    'price_unit': line.unit_price,
                    'tax_ids': [fields.Command.set(line.tax_ids.ids)],
                })
                for line in self.line_ids
            ],
        }
        move = self.env['account.move'].create(move_vals)
        self.account_move_id = move
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'views': [(False, 'form')],
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # CRON
    # -------------------------------------------------------------------------

    @api.model
    def cron_check_sdi_notifications(self):
        """Cron job: controlla notifiche SDI per tutte le fatture in attesa."""
        invoices = self.search([
            ('state', '=', 'sent'),
            ('sdi_file_id', '!=', False),
        ])
        _logger.info('Polling SDI: %d fatture da controllare', len(invoices))
        aruba = self.env['aruba.sdi.service']
        for invoice in invoices:
            try:
                aruba.check_notification(invoice)
            except Exception as e:
                _logger.error('Errore polling SDI per %s: %s', invoice.name, e)
        return True


class ForeignInvoiceSdiNotification(models.Model):
    _name = 'foreign.invoice.sdi.notification'
    _description = 'Notifica SDI Fattura Estera'
    _order = 'notification_date desc'

    import_id = fields.Many2one(
        'foreign.invoice.import',
        string='Fattura',
        required=True,
        ondelete='cascade',
    )
    notification_type = fields.Selection(
        selection=[
            ('RC', 'Ricevuta di Consegna'),
            ('NS', 'Notifica di Scarto'),
            ('MC', 'Notifica di Mancata Consegna'),
            ('NE', 'Notifica Esito Committente'),
            ('DT', 'Notifica Decorrenza Termini'),
            ('AT', 'Attestazione di avvenuta trasmissione'),
        ],
        string='Tipo Notifica',
        required=True,
    )
    notification_date = fields.Datetime(
        string='Data Notifica',
        required=True,
    )
    sdi_message_id = fields.Char(
        string='ID Messaggio SDI',
    )
    raw_content = fields.Text(
        string='Contenuto Grezzo',
    )
    xml_file = fields.Binary(
        string='File Notifica',
        attachment=True,
    )
    xml_filename = fields.Char(
        string='Nome File Notifica',
    )
