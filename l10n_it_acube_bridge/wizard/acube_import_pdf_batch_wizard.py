import base64
import json
import time
import zipfile
import io
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

POLL_MAX_ATTEMPTS = 20
POLL_INTERVAL_SECONDS = 3


class AcubeImportPdfBatchWizard(models.TransientModel):
    _name = 'acube.import.pdf.batch.wizard'
    _description = 'Importa più fatture estere da PDF via A-Cube AI (batch)'

    # -------------------------------------------------------------------------
    # Input
    # -------------------------------------------------------------------------

    upload_mode = fields.Selection([
        ('multi', 'File PDF multipli'),
        ('zip', 'File ZIP contenente PDF'),
    ], string='Modalità', default='multi')

    file_ids = fields.One2many('acube.import.pdf.batch.file', 'wizard_id', string='File PDF')

    zip_file = fields.Binary('File ZIP')
    zip_filename = fields.Char('Nome file ZIP')

    default_vat_rate = fields.Float('Aliquota IVA default (%)', default=22.0)
    convert_amounts = fields.Boolean('Converti importi in EUR', default=True)
    default_tipo_documento = fields.Selection([
        ('TD01', 'TD01 - Fattura'),
        ('TD04', 'TD04 - Nota di credito'),
        ('TD05', 'TD05 - Nota di debito'),
        ('TD17', 'TD17 - Autofattura servizi UE'),
        ('TD18', 'TD18 - Autofattura acquisti beni UE'),
        ('TD19', 'TD19 - Autofattura beni art.17 c.2'),
    ], string='Tipo Documento default', default='TD01')

    # -------------------------------------------------------------------------
    # Stato e risultati
    # -------------------------------------------------------------------------

    state = fields.Selection([
        ('upload', 'Carica File'),
        ('processing', 'Elaborazione'),
        ('done', 'Completato'),
    ], default='upload')

    total_files = fields.Integer('Totali', readonly=True)
    processed_files = fields.Integer('Elaborati', readonly=True)
    success_count = fields.Integer('Riusciti', readonly=True)
    error_count = fields.Integer('Errori', readonly=True)

    result_ids = fields.One2many('acube.import.pdf.batch.result', 'wizard_id', string='Risultati')

    # =====================================================================
    # AZIONE PRINCIPALE
    # =====================================================================

    def action_process_batch(self):
        """Elabora tutti i PDF caricati in sequenza."""
        self.ensure_one()

        # Raccogli tutti i PDF da elaborare
        pdf_list = self._collect_pdfs()
        if not pdf_list:
            raise UserError(_("Nessun file PDF da elaborare."))

        self.write({
            'state': 'processing',
            'total_files': len(pdf_list),
            'processed_files': 0,
            'success_count': 0,
            'error_count': 0,
        })

        mixin = self.env['acube.mixin']
        config_json = json.dumps({
            'default_vat_rate': self.default_vat_rate or 22,
            'convert_amounts': self.convert_amounts,
        })

        results = []
        success = 0
        errors = 0

        for idx, (filename, pdf_bytes) in enumerate(pdf_list, 1):
            _logger.info("Batch %d/%d: elaborazione %s", idx, len(pdf_list), filename)

            try:
                # 1. Upload PDF
                resp = mixin._acube_request(
                    'POST', '/invoice-extract',
                    files={'file': (filename, pdf_bytes, 'application/pdf')},
                    data={'conversion_configuration': config_json},
                )
                job_uuid = resp.json().get('uuid', '')
                if not job_uuid:
                    raise Exception("UUID non ricevuto da A-Cube")

                # 2. Polling
                result_json = self._poll_job(mixin, job_uuid)

                # 3. Scarica XML
                xml_resp = mixin._acube_request(
                    'GET', f'/invoice-extract/{job_uuid}/result',
                    headers={'Accept': 'application/xml'},
                )
                result_xml = xml_resp.text if xml_resp.status_code == 200 else ''

                # 4. Crea fattura
                invoice = self._create_invoice_from_json(
                    result_json, filename, pdf_bytes, result_xml,
                )

                results.append((0, 0, {
                    'filename': filename,
                    'status': 'success',
                    'invoice_id': invoice.id,
                    'message': f'Fattura {invoice.name} creata',
                }))
                success += 1

            except Exception as e:
                _logger.error("Batch errore su %s: %s", filename, str(e))
                results.append((0, 0, {
                    'filename': filename,
                    'status': 'error',
                    'message': str(e)[:500],
                }))
                errors += 1

            self.write({
                'processed_files': idx,
                'success_count': success,
                'error_count': errors,
            })

        self.write({
            'state': 'done',
            'result_ids': results,
        })

        return self._reopen()

    # =====================================================================
    # Helpers
    # =====================================================================

    def _collect_pdfs(self):
        """Raccoglie i PDF da elaborare. Restituisce lista di (filename, bytes)."""
        pdf_list = []

        if self.upload_mode == 'multi':
            for f in self.file_ids:
                if f.pdf_file:
                    pdf_list.append((
                        f.pdf_filename or f'fattura_{len(pdf_list)+1}.pdf',
                        base64.b64decode(f.pdf_file),
                    ))

        elif self.upload_mode == 'zip' and self.zip_file:
            zip_bytes = base64.b64decode(self.zip_file)
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
                    for name in zf.namelist():
                        # Ignora cartelle e file non-PDF
                        if name.endswith('/') or not name.lower().endswith('.pdf'):
                            continue
                        # Ignora file di sistema Mac
                        if name.startswith('__MACOSX') or name.startswith('.'):
                            continue
                        pdf_data = zf.read(name)
                        # Prendi solo il nome del file, non il percorso
                        clean_name = name.split('/')[-1]
                        pdf_list.append((clean_name, pdf_data))
            except zipfile.BadZipFile:
                raise UserError(_("Il file caricato non è un archivio ZIP valido."))

        return pdf_list

    def _poll_job(self, mixin, job_uuid):
        """Polling fino a success. Restituisce il JSON del risultato."""
        for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
            time.sleep(POLL_INTERVAL_SECONDS)
            try:
                resp = mixin._acube_request('GET', f'/invoice-extract/{job_uuid}')
            except Exception:
                continue

            status = resp.json().get('job_status', 'waiting')

            if status == 'success':
                result_resp = mixin._acube_request(
                    'GET', f'/invoice-extract/{job_uuid}/result',
                    headers={'Accept': 'application/json'},
                )
                if result_resp.status_code == 102:
                    continue
                return result_resp.json()

            if status == 'error':
                raise Exception(resp.json().get('error', 'Errore elaborazione A-Cube'))

        raise Exception("Timeout elaborazione PDF")

    def _create_invoice_from_json(self, result_json, filename, pdf_bytes, xml_text):
        """Crea fattura fornitore in bozza dai dati estratti."""
        # Parsa i dati del fornitore
        header = result_json.get('fattura_elettronica_header', {})
        cedente = header.get('cedente_prestatore', {})
        cedente_anag = cedente.get('dati_anagrafici', {})
        id_fiscale = cedente_anag.get('id_fiscale_iva', {})
        anagrafica = cedente_anag.get('anagrafica', {})

        id_paese = id_fiscale.get('id_paese', '')
        id_codice = id_fiscale.get('id_codice', '')
        vat = f"{id_paese}{id_codice}" if id_codice else ''
        name = (anagrafica.get('denominazione', '') or
                f"{anagrafica.get('nome', '')} {anagrafica.get('cognome', '')}".strip()
                or _('Fornitore estero'))

        # Cerca o crea partner
        partner = self._find_or_create_partner(vat, name, id_paese)

        # Dati documento
        bodies = result_json.get('fattura_elettronica_body', [])
        inv_number = ''
        inv_date = False
        invoice_lines = []

        if bodies:
            body = bodies[0]
            dati_gen = body.get('dati_generali', {}).get('dati_generali_documento', {})
            inv_number = dati_gen.get('numero', '')
            inv_date = dati_gen.get('data', False)

            linee = body.get('dati_beni_servizi', {}).get('dettaglio_linee', [])
            for linea in linee:
                desc = linea.get('descrizione', '')
                if not desc:
                    continue

                def sf(v, d=0.0):
                    try:
                        return float(v) if v else d
                    except (ValueError, TypeError):
                        return d

                tax = self._find_tax(sf(linea.get('aliquota_iva'), 22.0))
                lv = {
                    'name': desc,
                    'quantity': sf(linea.get('quantita'), 1.0),
                    'price_unit': sf(linea.get('prezzo_unitario')),
                }
                if tax:
                    lv['tax_ids'] = [(6, 0, [tax.id])]
                invoice_lines.append((0, 0, lv))

        if not invoice_lines:
            raise Exception(f"Nessuna riga estratta dal PDF {filename}")

        # Crea fattura
        invoice = self.env['account.move'].with_context(
            default_move_type='in_invoice',
        ).create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': inv_date or fields.Date.today(),
            'ref': inv_number,
            'acube_source': 'pdf_import',
            'invoice_line_ids': invoice_lines,
        })

        # Allega PDF originale
        self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_bytes),
            'res_model': 'account.move',
            'res_id': invoice.id,
            'mimetype': 'application/pdf',
        })

        # Allega XML — stesso nome del PDF con estensione .xml
        if xml_text:
            base_name = filename.rsplit('.', 1)[0]
            self.env['ir.attachment'].create({
                'name': f'{base_name}.xml',
                'type': 'binary',
                'datas': base64.b64encode(xml_text.encode('utf-8')),
                'res_model': 'account.move',
                'res_id': invoice.id,
                'mimetype': 'application/xml',
            })

        _logger.info("Batch: fattura %s creata da %s", invoice.name, filename)
        return invoice

    def _find_or_create_partner(self, vat, name, country_code):
        Partner = self.env['res.partner']
        partner = False

        if vat:
            partner = Partner.search([('vat', '=', vat)], limit=1)
            if not partner and len(vat) > 2:
                partner = Partner.search([('vat', 'ilike', vat[2:])], limit=1)

        if not partner and name:
            partner = Partner.search([('name', 'ilike', name)], limit=1)

        if not partner:
            country = False
            if country_code:
                country = self.env['res.country'].search([
                    ('code', '=', country_code.upper())
                ], limit=1)
            partner = Partner.create({
                'name': name or _('Fornitore estero'),
                'vat': vat or False,
                'is_company': True,
                'supplier_rank': 1,
                'country_id': country.id if country else False,
            })
        return partner

    def _find_tax(self, rate):
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


class AcubeImportPdfBatchFile(models.TransientModel):
    _name = 'acube.import.pdf.batch.file'
    _description = 'File PDF per import batch'

    wizard_id = fields.Many2one('acube.import.pdf.batch.wizard', required=True, ondelete='cascade')
    pdf_file = fields.Binary('File PDF', required=True)
    pdf_filename = fields.Char('Nome file')


class AcubeImportPdfBatchResult(models.TransientModel):
    _name = 'acube.import.pdf.batch.result'
    _description = 'Risultato import batch'

    wizard_id = fields.Many2one('acube.import.pdf.batch.wizard', required=True, ondelete='cascade')
    filename = fields.Char('File', readonly=True)
    status = fields.Selection([
        ('success', 'Riuscito'),
        ('error', 'Errore'),
    ], readonly=True)
    message = fields.Char('Dettaglio', readonly=True)
    invoice_id = fields.Many2one('account.move', 'Fattura', readonly=True)
