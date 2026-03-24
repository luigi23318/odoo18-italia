import base64
import json
import time
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

POLL_MAX_ATTEMPTS = 20
POLL_INTERVAL_SECONDS = 3


class AcubeImportPdfWizard(models.TransientModel):
    _name = 'acube.import.pdf.wizard'
    _description = 'Importa fattura estera da PDF via A-Cube AI'

    # --- Step 1: Upload ---
    pdf_file = fields.Binary('File PDF', required=True)
    pdf_filename = fields.Char('Nome file')
    default_vat_rate = fields.Float('Aliquota IVA default (%)', default=22.0)
    convert_amounts = fields.Boolean('Converti importi in EUR', default=True)
    default_tipo_documento = fields.Selection([
        ('TD01', 'TD01 - Fattura'),
        ('TD04', 'TD04 - Nota di credito'),
        ('TD05', 'TD05 - Nota di debito'),
        ('TD17', 'TD17 - Autofattura servizi UE'),
        ('TD18', 'TD18 - Autofattura acquisti beni UE'),
        ('TD19', 'TD19 - Autofattura beni art.17 c.2'),
    ], string='Tipo Documento default', default='TD01',
       help='Tipo documento preimpostato. Potrai modificarlo nella fase di revisione.')

    # --- Step 2: Processing ---
    job_uuid = fields.Char('UUID Job', readonly=True)
    job_status = fields.Selection([
        ('draft', 'Bozza'),
        ('waiting', 'In elaborazione...'),
        ('success', 'Completato'),
        ('error', 'Errore'),
    ], default='draft', readonly=True)
    job_error = fields.Text('Errore', readonly=True)

    # --- Step 3: Review ---
    extracted_json = fields.Text('JSON estratto', readonly=True)
    extracted_xml = fields.Text('XML generato', readonly=True)

    supplier_vat = fields.Char('P.IVA / VAT Fornitore')
    supplier_name = fields.Char('Ragione Sociale Fornitore')
    supplier_country_code = fields.Char('Codice Paese', size=2)
    invoice_number = fields.Char('Numero Fattura')
    invoice_date = fields.Date('Data Fattura')
    total_amount = fields.Float('Importo Totale (EUR)', digits=(16, 2))
    currency_code = fields.Char('Valuta originale', readonly=True)
    tipo_documento = fields.Selection([
        ('TD01', 'TD01 - Fattura'),
        ('TD04', 'TD04 - Nota di credito'),
        ('TD05', 'TD05 - Nota di debito'),
        ('TD17', 'TD17 - Autofattura servizi UE'),
        ('TD18', 'TD18 - Autofattura acquisti beni UE'),
        ('TD19', 'TD19 - Autofattura beni art.17 c.2'),
    ], string='Tipo Documento', default='TD01')
    line_ids = fields.One2many('acube.import.pdf.wizard.line', 'wizard_id', string='Righe')

    invoice_id = fields.Many2one('account.move', 'Fattura creata', readonly=True)
    state = fields.Selection([
        ('upload', 'Carica PDF'),
        ('processing', 'Elaborazione'),
        ('review', 'Rivedi e Crea'),
        ('done', 'Completato'),
    ], default='upload')

    # =====================================================================
    # STEP 1 → 2: Upload e avvia estrazione
    # =====================================================================

    def action_upload_and_extract(self):
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_("Seleziona un file PDF."))

        mixin = self.env['acube.mixin']
        pdf_bytes = base64.b64decode(self.pdf_file)

        # config_json rimosso - A-Cube usa i default

        _logger.info("A-Cube Extract: upload %s (%d bytes)", self.pdf_filename or 'invoice.pdf', len(pdf_bytes))

        try:
            response = mixin._acube_request(
                'POST', '/invoice-extract',
                files={'file': (self.pdf_filename or 'invoice.pdf', pdf_bytes, 'application/pdf')},
            )
        except Exception as e:
            raise UserError(_("Errore upload PDF: %s") % str(e))

        data = response.json()
        job_uuid = data.get('uuid', '')
        if not job_uuid:
            raise UserError(_("A-Cube non ha restituito UUID. Risposta: %s") % json.dumps(data))

        _logger.info("A-Cube Extract: job avviato UUID=%s", job_uuid)
        self.write({'job_uuid': job_uuid, 'job_status': 'waiting', 'state': 'processing'})
        return self._poll_for_result()

    # =====================================================================
    # STEP 2: Polling
    # =====================================================================

    def _poll_for_result(self):
        self.ensure_one()
        mixin = self.env['acube.mixin']

        for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
            time.sleep(POLL_INTERVAL_SECONDS)
            try:
                resp = mixin._acube_request('GET', f'/invoice-extract/{self.job_uuid}')
            except Exception as e:
                _logger.warning("Poll %d/%d fallito: %s", attempt, POLL_MAX_ATTEMPTS, e)
                continue

            status = resp.json().get('job_status', 'waiting')
            _logger.debug("Poll %d/%d: status=%s", attempt, POLL_MAX_ATTEMPTS, status)

            if status == 'success':
                return self._fetch_and_populate()
            if status == 'error':
                error_msg = resp.json().get('error', 'Errore sconosciuto')
                self.write({'job_status': 'error', 'job_error': error_msg, 'state': 'upload'})
                raise UserError(_("Errore A-Cube: %s") % error_msg)

        self.write({'job_status': 'error', 'job_error': 'Timeout', 'state': 'upload'})
        raise UserError(_("Timeout: elaborazione troppo lunga. Riprova."))

    def _fetch_and_populate(self):
        self.ensure_one()
        mixin = self.env['acube.mixin']

        json_resp = mixin._acube_request(
            'GET', f'/invoice-extract/{self.job_uuid}/result',
            headers={'Accept': 'application/json'},
        )
        if json_resp.status_code == 102:
            raise UserError(_("Risultato non ancora pronto. Riprova."))

        result_json = json_resp.json()

        xml_resp = mixin._acube_request(
            'GET', f'/invoice-extract/{self.job_uuid}/result',
            headers={'Accept': 'application/xml'},
        )
        result_xml = xml_resp.text if xml_resp.status_code == 200 else ''

        _logger.info("A-Cube Extract result:\n%s", json.dumps(result_json, indent=2, ensure_ascii=False)[:3000])

        self.write({
            'job_status': 'success',
            'extracted_json': json.dumps(result_json, indent=2, ensure_ascii=False),
            'extracted_xml': result_xml,
            'state': 'review',
        })
        self._populate_from_json(result_json)
        return self._reopen()

    # =====================================================================
    # STEP 3: Popola campi review dal JSON
    # =====================================================================

    def _populate_from_json(self, data):
        self.ensure_one()
        header = data.get('fattura_elettronica_header', {})
        cedente = header.get('cedente_prestatore', {})
        cedente_anag = cedente.get('dati_anagrafici', {})
        id_fiscale = cedente_anag.get('id_fiscale_iva', {})
        anagrafica = cedente_anag.get('anagrafica', {})

        id_paese = id_fiscale.get('id_paese', '')
        id_codice = id_fiscale.get('id_codice', '')

        vals = {
            'supplier_vat': f"{id_paese}{id_codice}" if id_codice else '',
            'supplier_name': anagrafica.get('denominazione', '') or
                f"{anagrafica.get('nome', '')} {anagrafica.get('cognome', '')}".strip(),
            'supplier_country_code': id_paese,
        }

        bodies = data.get('fattura_elettronica_body', [])
        if bodies:
            body = bodies[0]
            dati_gen = body.get('dati_generali', {}).get('dati_generali_documento', {})
            vals['invoice_number'] = dati_gen.get('numero', '')
            vals['invoice_date'] = dati_gen.get('data', False)
            vals['currency_code'] = dati_gen.get('divisa', 'EUR')

            total_str = dati_gen.get('importo_totale_documento', '')
            try:
                vals['total_amount'] = float(total_str) if total_str else 0.0
            except (ValueError, TypeError):
                vals['total_amount'] = 0.0

            tipo_doc = dati_gen.get('tipo_documento', '')
            if tipo_doc in dict(self._fields['tipo_documento'].selection):
                vals['tipo_documento'] = tipo_doc
            else:
                vals['tipo_documento'] = self.default_tipo_documento or 'TD01'

            linee = body.get('dati_beni_servizi', {}).get('dettaglio_linee', [])
            line_vals = [(5, 0, 0)]
            for linea in linee:
                ld = self._parse_line(linea)
                if ld:
                    line_vals.append((0, 0, ld))
            vals['line_ids'] = line_vals

        self.write(vals)

    def _parse_line(self, linea):
        desc = linea.get('descrizione', '')
        if not desc:
            return None

        def sf(v, d=0.0):
            try:
                return float(v) if v else d
            except (ValueError, TypeError):
                return d

        return {
            'description': desc,
            'quantity': sf(linea.get('quantita'), 1.0),
            'price_unit': sf(linea.get('prezzo_unitario')),
            'vat_rate': sf(linea.get('aliquota_iva'), 22.0),
        }

    # =====================================================================
    # STEP 3 → Done: Crea fattura
    # =====================================================================

    def action_create_invoice(self):
        self.ensure_one()
        if not self.supplier_name and not self.supplier_vat:
            raise UserError(_("Inserisci almeno la ragione sociale o P.IVA del fornitore."))

        partner = self._find_or_create_supplier()

        invoice_lines = []
        for line in self.line_ids:
            tax = self._find_purchase_tax(line.vat_rate)
            lv = {
                'name': line.description or '/',
                'quantity': line.quantity,
                'price_unit': line.price_unit,
            }
            if tax:
                lv['tax_ids'] = [(6, 0, [tax.id])]
            invoice_lines.append((0, 0, lv))

        if not invoice_lines:
            raise UserError(_("Nessuna riga da importare."))

        invoice = self.env['account.move'].with_context(
            default_move_type='in_invoice',
        ).create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': self.invoice_date or fields.Date.today(),
            'ref': self.invoice_number or '',
            'acube_source': 'pdf_import',
            'invoice_line_ids': invoice_lines,
        })

        # Allega PDF originale
        if self.pdf_file:
            self.env['ir.attachment'].create({
                'name': self.pdf_filename or 'fattura.pdf',
                'type': 'binary',
                'datas': self.pdf_file,
                'res_model': 'account.move',
                'res_id': invoice.id,
                'mimetype': 'application/pdf',
            })

        # Allega XML — stesso nome del PDF ma con estensione .xml
        if self.extracted_xml:
            base_name = (self.pdf_filename or 'fattura').rsplit('.', 1)[0]
            self.env['ir.attachment'].create({
                'name': f'{base_name}.xml',
                'type': 'binary',
                'datas': base64.b64encode(self.extracted_xml.encode('utf-8')),
                'res_model': 'account.move',
                'res_id': invoice.id,
                'mimetype': 'application/xml',
            })

        self.write({'invoice_id': invoice.id, 'state': 'done'})
        _logger.info("Fattura creata: %s (id=%d)", invoice.name, invoice.id)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # =====================================================================
    # Helpers
    # =====================================================================

    def _find_or_create_supplier(self):
        Partner = self.env['res.partner']
        partner = False

        if self.supplier_vat:
            vat = self.supplier_vat.strip()
            partner = Partner.search([('vat', '=', vat)], limit=1)
            if not partner and len(vat) > 2:
                partner = Partner.search([('vat', 'ilike', vat[2:])], limit=1)

        if not partner and self.supplier_name:
            partner = Partner.search([('name', 'ilike', self.supplier_name.strip())], limit=1)

        if not partner:
            country = False
            if self.supplier_country_code:
                country = self.env['res.country'].search([
                    ('code', '=', self.supplier_country_code.upper())
                ], limit=1)
            partner = Partner.create({
                'name': self.supplier_name or _('Fornitore estero'),
                'vat': self.supplier_vat or False,
                'is_company': True,
                'supplier_rank': 1,
                'country_id': country.id if country else False,
            })
        return partner

    def _find_purchase_tax(self, rate):
        if not rate:
            return False
        tax = self.env['account.tax'].search([
            ('type_tax_use', '=', 'purchase'),
            ('amount', '=', rate),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not tax:
            tax = self.env['account.tax'].search([
                ('type_tax_use', '=', 'purchase'),
                ('company_id', '=', self.env.company.id),
            ], order='amount', limit=1)
        return tax

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class AcubeImportPdfWizardLine(models.TransientModel):
    _name = 'acube.import.pdf.wizard.line'
    _description = 'Riga fattura estratta da PDF'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('acube.import.pdf.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    description = fields.Char('Descrizione', required=True)
    quantity = fields.Float('Quantità', default=1.0, digits=(16, 4))
    price_unit = fields.Float('Prezzo Unitario', digits=(16, 2))
    vat_rate = fields.Float('Aliquota IVA (%)', default=22.0)
    subtotal = fields.Float('Subtotale', compute='_compute_subtotal', digits=(16, 2))

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit
