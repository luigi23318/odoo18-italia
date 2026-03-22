import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

STATO_SELECTION = [
    ('bozza', 'Bozza'),
    ('testo_estratto', 'Testo estratto'),
    ('dati_estratti', 'Dati estratti'),
    ('nessun_template', 'Nessun template'),
    ('in_revisione', 'In revisione'),
    ('validato', 'Validato'),
    ('xml_generato', 'XML generato'),
    ('inviato_sdi', 'Inviato allo SDI'),
    ('consegnato', 'Consegnato'),
    ('scartato', 'Scartato'),
    ('registrato', 'Registrato'),
]

TIPO_DOCUMENTO_SELECTION = [
    ('TD17', 'TD17 - Servizi da fornitore estero'),
    ('TD18', 'TD18 - Beni intracomunitari UE'),
    ('TD19', 'TD19 - Beni già in Italia da fornitore estero'),
]

NATURA_CODE_SELECTION = [
    ('N2.1', 'N2.1 - Non soggette art. 7'),
    ('N2.2', 'N2.2 - Non soggette - altri casi'),
    ('N3.4', 'N3.4 - Non imponibili cessioni intracomunitarie'),
    ('N3.6', 'N3.6 - Non imponibili - altri casi'),
    ('N4', 'N4 - Esenti'),
]

DESCRIPTION_TYPE_SELECTION = [
    ('BENI', 'Beni'),
    ('SERVIZI', 'Servizi'),
    ('BENI E SERVIZI', 'Beni e servizi'),
]

SDI_STATE_SELECTION = [
    ('pending', 'In attesa'),
    ('sent', 'Inviato'),
    ('delivered', 'Consegnato'),
    ('rejected', 'Scartato'),
]


class ForeignInvoiceImport(models.Model):
    _name = 'foreign.invoice.import'
    _description = 'Importazione fattura estera'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Riferimento',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nuovo'),
    )
    state = fields.Selection(
        selection=STATO_SELECTION,
        string='Stato',
        default='bozza',
        required=True,
        tracking=True,
    )
    extraction_engine = fields.Selection(
        selection=[('tesseract', 'Tesseract OCR'), ('acube', 'A-Cube API')],
        string='Motore estrazione',
        readonly=True,
    )
    batch_id = fields.Many2one(
        'foreign.invoice.batch',
        string='Batch',
        ondelete='set null',
    )

    # PDF e XML
    pdf_attachment_id = fields.Many2one(
        'ir.attachment',
        string='PDF originale',
        ondelete='set null',
    )
    pdf_filename = fields.Char(
        string='Nome file PDF',
        related='pdf_attachment_id.name',
    )
    xml_attachment_id = fields.Many2one(
        'ir.attachment',
        string='XML FatturaPA',
        ondelete='set null',
    )
    xml_filename = fields.Char(
        string='Nome file XML',
    )
    xml_content = fields.Text(
        string='Contenuto XML',
        readonly=True,
    )

    # OCR
    raw_text = fields.Text(
        string='Testo grezzo OCR',
        readonly=True,
    )
    template_matched = fields.Boolean(
        string='Template trovato',
        default=False,
    )

    # Dati fattura
    tipo_documento = fields.Selection(
        selection=TIPO_DOCUMENTO_SELECTION,
        string='Tipo documento',
        tracking=True,
    )
    supplier_name = fields.Char(string='Denominazione fornitore')
    supplier_vat = fields.Char(string='P.IVA / Tax ID fornitore')
    supplier_country_id = fields.Many2one(
        'res.country',
        string='Paese fornitore',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Fornitore Odoo',
    )
    invoice_number = fields.Char(string='Numero fattura originale')
    invoice_date = fields.Date(string='Data fattura originale')
    reception_date = fields.Date(
        string='Data ricezione',
        default=fields.Date.context_today,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Valuta',
        default=lambda self: self.env.company.currency_id,
    )
    amount_untaxed = fields.Float(string='Imponibile netto', digits=(16, 2))
    amount_tax_foreign = fields.Float(
        string='IVA estera (informativo)',
        digits=(16, 2),
    )
    amount_total = fields.Float(string='Totale fattura', digits=(16, 2))

    # IVA italiana
    it_tax_id = fields.Many2one(
        'account.tax',
        string='Aliquota IVA italiana',
        domain=[('type_tax_use', '=', 'purchase')],
    )
    natura_code = fields.Selection(
        selection=NATURA_CODE_SELECTION,
        string='Codice Natura',
    )
    description_type = fields.Selection(
        selection=DESCRIPTION_TYPE_SELECTION,
        string='Tipo descrizione',
        default='SERVIZI',
    )

    # Righe
    line_ids = fields.One2many(
        'foreign.invoice.import.line',
        'import_id',
        string='Righe dettaglio',
    )

    # SDI
    sdi_state = fields.Selection(
        selection=SDI_STATE_SELECTION,
        string='Stato SDI',
    )
    sdi_id = fields.Char(string='ID SDI')
    sdi_filename = fields.Char(string='Nome file SDI')

    # Contabilità
    account_move_id = fields.Many2one(
        'account.move',
        string='Registrazione contabile',
        readonly=True,
    )

    # Validazione
    validation_errors = fields.Text(string='Errori di validazione')

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> 'ForeignInvoiceImport':
        for vals in vals_list:
            if vals.get('name', _('Nuovo')) == _('Nuovo'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'foreign.invoice.import'
                ) or _('Nuovo')
        return super().create(vals_list)

    def action_extract(self) -> None:
        """Estrae dati dal PDF usando il motore configurato."""
        self.ensure_one()
        if not self.pdf_attachment_id:
            raise UserError(_('Caricare un PDF prima di estrarre i dati.'))

        ICP = self.env['ir.config_parameter'].sudo()
        engine = ICP.get_param('foreign_invoice.extraction_engine', 'tesseract')
        self.extraction_engine = engine

        if engine == 'tesseract':
            self._extract_with_tesseract()
        elif engine == 'acube':
            self._extract_with_acube()
        else:
            raise UserError(_('Motore di estrazione non configurato.'))

    def _extract_with_tesseract(self) -> None:
        """Estrazione via pdfplumber + Tesseract + invoice2data."""
        from ..services.ocr_service import OcrService
        from ..services.extraction_service import ExtractionService

        ICP = self.env['ir.config_parameter'].sudo()
        languages = ICP.get_param(
            'foreign_invoice.ocr_languages', 'ita+eng+deu+fra+spa'
        )

        _logger.info('Estrazione Tesseract per %s', self.name)

        ocr = OcrService()
        raw_text = ocr.extract_text(self.pdf_attachment_id, languages)
        self.raw_text = raw_text
        self.state = 'testo_estratto'

        use_templates = ICP.get_param(
            'foreign_invoice.use_builtin_templates', 'True'
        )
        if use_templates in ('True', 'true', '1', True):
            extractor = ExtractionService()
            result = extractor.extract_fields(raw_text)
            if result:
                self._apply_extracted_data(result)
                self.template_matched = True
                self.state = 'dati_estratti'
            else:
                self.template_matched = False
                self.state = 'nessun_template'
        else:
            self.state = 'nessun_template'

        _logger.info(
            'Estrazione Tesseract completata per %s: stato=%s',
            self.name, self.state,
        )

    def _extract_with_acube(self) -> None:
        """Estrazione via A-Cube API cloud."""
        from ..services.acube_extraction_service import AcubeExtractionService

        _logger.info('Estrazione A-Cube per %s', self.name)

        try:
            service = AcubeExtractionService(self.env)
            result = service.extract_invoice(self.pdf_attachment_id)
            if result:
                self._apply_extracted_data(result)
                self.template_matched = True
                self.state = 'dati_estratti'
            else:
                self.state = 'bozza'
                self.validation_errors = _(
                    'A-Cube non ha restituito dati per questo PDF.'
                )
        except Exception as e:
            _logger.exception('Errore estrazione A-Cube per %s', self.name)
            self.state = 'bozza'
            self.validation_errors = str(e)

        _logger.info(
            'Estrazione A-Cube completata per %s: stato=%s',
            self.name, self.state,
        )

    def _apply_extracted_data(self, data: dict) -> None:
        """Applica i dati estratti ai campi del record."""
        vals = {}
        if data.get('invoice_number'):
            vals['invoice_number'] = data['invoice_number']
        if data.get('invoice_date'):
            vals['invoice_date'] = data['invoice_date']
        if data.get('supplier_name'):
            vals['supplier_name'] = data['supplier_name']
        if data.get('supplier_vat'):
            vals['supplier_vat'] = data['supplier_vat']
        if data.get('amount_untaxed'):
            vals['amount_untaxed'] = float(data['amount_untaxed'])
        if data.get('amount_tax'):
            vals['amount_tax_foreign'] = float(data['amount_tax'])
        if data.get('amount_total'):
            vals['amount_total'] = float(data['amount_total'])
        if data.get('tipo_documento'):
            vals['tipo_documento'] = data['tipo_documento']
        if data.get('description_type'):
            vals['description_type'] = data['description_type']

        # Currency
        currency_code = data.get('currency_code')
        if currency_code:
            currency = self.env['res.currency'].search(
                [('name', '=', currency_code)], limit=1
            )
            if currency:
                vals['currency_id'] = currency.id

        # Country
        country_code = data.get('country_code')
        if country_code:
            country = self.env['res.country'].search(
                [('code', '=', country_code.upper())], limit=1
            )
            if country:
                vals['supplier_country_id'] = country.id

        # Partner match per VAT
        supplier_vat = data.get('supplier_vat')
        if supplier_vat:
            partner = self.env['res.partner'].search(
                [('vat', '=', supplier_vat)], limit=1
            )
            if not partner:
                partner = self.env['res.partner'].search(
                    [('vat', 'ilike', supplier_vat)], limit=1
                )
            if partner:
                vals['partner_id'] = partner.id

        self.write(vals)

        # Line items
        line_items = data.get('line_items', [])
        if line_items:
            self.line_ids.unlink()
            for li in line_items:
                self.env['foreign.invoice.import.line'].create({
                    'import_id': self.id,
                    'description': li.get('description', ''),
                    'quantity': float(li.get('quantity', 1)),
                    'unit_price': float(li.get('unit_price', 0)),
                    'line_total': float(li.get('total', 0)),
                    'tax_rate_foreign': float(li.get('tax_rate', 0)),
                })

    def action_set_in_review(self) -> None:
        """Porta la fattura in stato revisione."""
        for rec in self:
            if rec.state in ('dati_estratti', 'nessun_template', 'bozza'):
                rec.state = 'in_revisione'

    def action_validate(self) -> None:
        """Valida la fattura dopo revisione operatore."""
        for rec in self:
            errors = rec._check_validation()
            if errors:
                rec.validation_errors = '\n'.join(errors)
                raise UserError(
                    _('Errori di validazione:\n%s') % '\n'.join(errors)
                )
            rec.validation_errors = False
            rec.state = 'validato'

    def _check_validation(self) -> list[str]:
        """Verifica campi obbligatori per validazione."""
        errors = []
        if not self.tipo_documento:
            errors.append(_('Tipo documento (TD) obbligatorio.'))
        if not self.supplier_name:
            errors.append(_('Denominazione fornitore obbligatoria.'))
        if not self.supplier_country_id:
            errors.append(_('Paese fornitore obbligatorio.'))
        if not self.invoice_number:
            errors.append(_('Numero fattura originale obbligatorio.'))
        if not self.invoice_date:
            errors.append(_('Data fattura originale obbligatoria.'))
        if not self.reception_date:
            errors.append(_('Data ricezione obbligatoria.'))
        if not self.amount_untaxed and not self.amount_total:
            errors.append(_('Importo obbligatorio.'))
        if not self.description_type:
            errors.append(_('Tipo descrizione (Beni/Servizi) obbligatorio.'))
        return errors

    def action_generate_xml(self) -> None:
        """Genera XML FatturaPA."""
        for rec in self:
            if rec.state != 'validato':
                raise UserError(
                    _('La fattura deve essere validata prima di generare XML.')
                )
            generator = self.env['fatturapa.xml.generator']
            xml_content, filename = generator.generate_xml(rec)
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(xml_content.encode('utf-8')),
                'res_model': self._name,
                'res_id': rec.id,
                'mimetype': 'application/xml',
            })
            rec.write({
                'xml_attachment_id': attachment.id,
                'xml_filename': filename,
                'xml_content': xml_content,
                'state': 'xml_generato',
            })
            _logger.info('XML generato per %s: %s', rec.name, filename)

    def action_send_sdi(self) -> None:
        """Invia XML allo SDI via Aruba Premium API."""
        for rec in self:
            if rec.state != 'xml_generato':
                raise UserError(
                    _('Generare prima l\'XML FatturaPA.')
                )
            sdi_service = self.env['aruba.sdi.service']
            sdi_service.send_invoice(rec)

    def action_download_xml(self) -> dict:
        """Scarica XML sul PC dell'operatore."""
        self.ensure_one()
        if not self.xml_attachment_id:
            raise UserError(_('Nessun XML generato.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.xml_attachment_id.id,
            'target': 'self',
        }

    def action_download_pdf(self) -> dict:
        """Scarica PDF originale sul PC dell'operatore."""
        self.ensure_one()
        if not self.pdf_attachment_id:
            raise UserError(_('Nessun PDF caricato.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.pdf_attachment_id.id,
            'target': 'self',
        }

    def action_register_accounting(self) -> None:
        """Registra la fattura in contabilità."""
        for rec in self:
            if rec.state not in ('consegnato', 'xml_generato', 'inviato_sdi'):
                raise UserError(
                    _('La fattura deve essere almeno in stato XML generato.')
                )
            if rec.account_move_id:
                raise UserError(
                    _('Registrazione contabile già presente.')
                )
            rec._create_account_move()
            rec.state = 'registrato'

    def _create_account_move(self) -> None:
        """Crea account.move con reverse charge."""
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            partner = self._find_or_create_partner()
            self.partner_id = partner

        move_vals = {
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': self.reception_date or self.invoice_date,
            'ref': self.invoice_number,
            'currency_id': self.currency_id.id,
            'invoice_line_ids': [],
        }

        if self.line_ids:
            for line in self.line_ids:
                move_vals['invoice_line_ids'].append((0, 0, {
                    'name': line.description or self.description_type or '/',
                    'quantity': line.quantity or 1,
                    'price_unit': line.unit_price,
                    'tax_ids': [(6, 0, [self.it_tax_id.id])] if self.it_tax_id else [],
                }))
        else:
            move_vals['invoice_line_ids'].append((0, 0, {
                'name': self.description_type or 'Fattura estera',
                'quantity': 1,
                'price_unit': self.amount_untaxed or self.amount_total,
                'tax_ids': [(6, 0, [self.it_tax_id.id])] if self.it_tax_id else [],
            }))

        move = self.env['account.move'].create(move_vals)

        # Collega allegati
        if self.pdf_attachment_id:
            self.pdf_attachment_id.copy({
                'res_model': 'account.move',
                'res_id': move.id,
            })
        if self.xml_attachment_id:
            self.xml_attachment_id.copy({
                'res_model': 'account.move',
                'res_id': move.id,
            })

        self.account_move_id = move
        _logger.info(
            'Registrazione contabile creata: %s per %s',
            move.name, self.name,
        )

    def _find_or_create_partner(self) -> 'res.partner':
        """Trova o crea il partner fornitore."""
        self.ensure_one()
        if self.supplier_vat:
            partner = self.env['res.partner'].search(
                [('vat', 'ilike', self.supplier_vat)], limit=1
            )
            if partner:
                return partner

        return self.env['res.partner'].create({
            'name': self.supplier_name or _('Fornitore estero'),
            'vat': self.supplier_vat or False,
            'country_id': self.supplier_country_id.id if self.supplier_country_id else False,
            'supplier_rank': 1,
            'company_type': 'company',
        })

    def action_reset_to_draft(self) -> None:
        """Riporta in bozza."""
        for rec in self:
            if rec.state == 'registrato':
                raise UserError(
                    _('Impossibile riportare in bozza una fattura registrata.')
                )
            rec.state = 'bozza'
