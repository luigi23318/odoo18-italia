import base64
import json
import time
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Polling: max tentativi e intervallo in secondi
POLL_MAX_ATTEMPTS = 20
POLL_INTERVAL_SECONDS = 3


class AcubeImportPdfWizard(models.TransientModel):
    _name = 'acube.import.pdf.wizard'
    _description = 'Importa fattura estera da PDF via A-Cube AI'

    # -------------------------------------------------------------------------
    # Step 1: Upload
    # -------------------------------------------------------------------------

    pdf_file = fields.Binary(
        string='File PDF',
        required=True,
        help="Il file PDF della fattura estera da convertire.",
    )
    pdf_filename = fields.Char('Nome file')

    default_vat_rate = fields.Float(
        string='Aliquota IVA default (%)',
        default=22.0,
        help="Aliquota IVA applicata alle righe se non rilevata dal PDF.",
    )
    convert_amounts = fields.Boolean(
        string='Converti importi in EUR',
        default=True,
        help="Se attivo, converte gli importi nella valuta originale in EUR "
             "usando il tasso di cambio ufficiale della Banca d'Italia.",
    )

    # -------------------------------------------------------------------------
    # Step 2: Processing
    # -------------------------------------------------------------------------

    job_uuid = fields.Char('UUID Job', readonly=True)
    job_status = fields.Selection(
        selection=[
            ('draft', 'Bozza'),
            ('waiting', 'In elaborazione...'),
            ('success', 'Completato'),
            ('error', 'Errore'),
        ],
        default='draft',
        readonly=True,
    )
    job_error = fields.Text('Errore elaborazione', readonly=True)

    # -------------------------------------------------------------------------
    # Step 3: Review — dati estratti dall'AI, modificabili dall'utente
    # -------------------------------------------------------------------------

    # Dati grezzi (per debug e allegati)
    extracted_json = fields.Text('Dati estratti (JSON)', readonly=True)
    extracted_xml = fields.Text('XML FatturaPA generato', readonly=True)

    # Dati fornitore
    supplier_vat = fields.Char('P.IVA / VAT Fornitore')
    supplier_name = fields.Char('Ragione Sociale Fornitore')
    supplier_country_code = fields.Char('Codice Paese Fornitore', size=2)

    # Dati documento
    invoice_number = fields.Char('Numero Fattura')
    invoice_date = fields.Date('Data Fattura')
    total_amount = fields.Float('Importo Totale (EUR)', digits=(16, 2))
    currency_code = fields.Char('Valuta originale', readonly=True)

    tipo_documento = fields.Selection(
        selection=[
            ('TD01', 'TD01 - Fattura'),
            ('TD04', 'TD04 - Nota di credito'),
            ('TD05', 'TD05 - Nota di debito'),
            ('TD17', 'TD17 - Autofattura servizi UE'),
            ('TD18', 'TD18 - Autofattura acquisti beni UE'),
            ('TD19', 'TD19 - Autofattura beni art.17 c.2'),
        ],
        string='Tipo Documento',
        default='TD01',
        help="L'AI NON determina automaticamente il tipo documento per le autofatture.\n"
             "Seleziona manualmente il tipo corretto:\n"
             "- TD17: integrazione/autofattura per acquisto servizi dall'estero\n"
             "- TD18: integrazione per acquisto beni intracomunitari\n"
             "- TD19: integrazione per acquisto beni art.17 c.2 DPR 633/72",
    )

    # Righe fattura
    line_ids = fields.One2many(
        'acube.import.pdf.wizard.line', 'wizard_id',
        string='Righe fattura',
    )

    # Risultato
    invoice_id = fields.Many2one('account.move', 'Fattura creata', readonly=True)

    # Stato wizard
    state = fields.Selection(
        selection=[
            ('upload', 'Carica PDF'),
            ('processing', 'Elaborazione'),
            ('review', 'Rivedi e Crea'),
            ('done', 'Completato'),
        ],
        default='upload',
    )

    # =====================================================================
    # AZIONI
    # =====================================================================

    def action_upload_and_extract(self):
        """Step 1 → 2: Carica PDF su A-Cube, avvia estrazione AI, attendi risultato."""
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_("Seleziona un file PDF da caricare."))

        mixin = self.env['acube.mixin']

        # Decodifica il file dal campo Binary di Odoo
        pdf_bytes = base64.b64decode(self.pdf_file)

        # Configurazione conversione come stringa JSON
        config_json = json.dumps({
            'default_vat_rate': self.default_vat_rate or 22,
            'convert_amounts': self.convert_amounts,
        })

        _logger.info(
            "A-Cube Invoice Extract: upload %s (%d bytes), config: %s",
            self.pdf_filename or 'invoice.pdf', len(pdf_bytes), config_json,
        )

        # POST /invoice-extract (multipart/form-data)
        try:
            response = mixin._acube_request(
                'POST', '/invoice-extract',
                files={
                    'file': (
                        self.pdf_filename or 'invoice.pdf',
                        pdf_bytes,
                        'application/pdf',
                    ),
                },
                data={
                    'conversion_configuration': config_json,
                },
            )
        except Exception as e:
            raise UserError(_(
                "Errore nell'upload del PDF su A-Cube:\n%s"
            ) % str(e))

        data = response.json()
        job_uuid = data.get('uuid', '')
        if not job_uuid:
            raise UserError(_(
                "A-Cube non ha restituito un UUID per il job.\nRisposta: %s"
            ) % json.dumps(data, indent=2))

        _logger.info("A-Cube Invoice Extract: job avviato, UUID=%s", job_uuid)

        self.write({
            'job_uuid': job_uuid,
            'job_status': 'waiting',
            'state': 'processing',
        })

        # Polling sincrono — attendi il completamento
        return self._poll_for_result()

    def _poll_for_result(self):
        """Polling sull'endpoint di stato fino a success/error, poi passa a review."""
        self.ensure_one()
        mixin = self.env['acube.mixin']

        for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
            time.sleep(POLL_INTERVAL_SECONDS)

            try:
                status_resp = mixin._acube_request(
                    'GET', f'/invoice-extract/{self.job_uuid}',
                )
            except Exception as e:
                _logger.warning(
                    "A-Cube poll attempt %d/%d failed: %s",
                    attempt, POLL_MAX_ATTEMPTS, e,
                )
                continue

            status_data = status_resp.json()
            job_status = status_data.get('job_status', 'waiting')

            _logger.debug(
                "A-Cube poll %d/%d: status=%s",
                attempt, POLL_MAX_ATTEMPTS, job_status,
            )

            if job_status == 'success':
                return self._fetch_and_populate_result()

            if job_status == 'error':
                error_msg = status_data.get('error', 'Errore sconosciuto durante l\'elaborazione')
                self.write({
                    'job_status': 'error',
                    'job_error': error_msg,
                    'state': 'upload',
                })
                raise UserError(_(
                    "A-Cube: errore nell'elaborazione del PDF.\n%s"
                ) % error_msg)

        # Timeout raggiunto
        self.write({
            'job_status': 'error',
            'job_error': 'Timeout: elaborazione troppo lunga',
            'state': 'upload',
        })
        raise UserError(_(
            "L'elaborazione del PDF sta impiegando troppo tempo.\n"
            "Riprova tra qualche minuto."
        ))

    def _fetch_and_populate_result(self):
        """Scarica il risultato JSON e XML, popola i campi review."""
        self.ensure_one()
        mixin = self.env['acube.mixin']

        # Scarica risultato JSON
        json_resp = mixin._acube_request(
            'GET', f'/invoice-extract/{self.job_uuid}/result',
            headers={'Accept': 'application/json'},
        )
        # Gestisci response 102 (non ancora pronto)
        if json_resp.status_code == 102:
            raise UserError(_("Il risultato non è ancora pronto. Riprova tra qualche secondo."))

        result_json = json_resp.json()

        # Scarica risultato XML
        xml_resp = mixin._acube_request(
            'GET', f'/invoice-extract/{self.job_uuid}/result',
            headers={'Accept': 'application/xml'},
        )
        result_xml = xml_resp.text if xml_resp.status_code == 200 else ''

        # Logga il JSON completo per debug (importante per i primi test!)
        _logger.info(
            "A-Cube Invoice Extract risultato JSON:\n%s",
            json.dumps(result_json, indent=2, ensure_ascii=False)[:5000],
        )

        self.write({
            'job_status': 'success',
            'extracted_json': json.dumps(result_json, indent=2, ensure_ascii=False),
            'extracted_xml': result_xml,
            'state': 'review',
        })

        # Popola i campi di review
        self._populate_from_extracted_json(result_json)

        return self._reopen_wizard()

    def _populate_from_extracted_json(self, data):
        """Parsa il JSON FatturaPA restituito da A-Cube e popola i campi del wizard.

        NOTA: La struttura esatta del JSON dipende dal PDF analizzato.
        Al primo test in sandbox, logga il JSON completo e adatta questo metodo
        se la struttura differisce da quella attesa.
        """
        self.ensure_one()

        # --- Header ---
        header = data.get('fattura_elettronica_header', {})

        # Cedente/Prestatore (fornitore)
        cedente = header.get('cedente_prestatore', {})
        cedente_anag = cedente.get('dati_anagrafici', {})
        id_fiscale = cedente_anag.get('id_fiscale_iva', {})
        anagrafica = cedente_anag.get('anagrafica', {})

        id_paese = id_fiscale.get('id_paese', '')
        id_codice = id_fiscale.get('id_codice', '')

        vals = {
            'supplier_vat': f"{id_paese}{id_codice}" if id_codice else '',
            'supplier_name': (
                anagrafica.get('denominazione', '') or
                f"{anagrafica.get('nome', '')} {anagrafica.get('cognome', '')}".strip()
            ),
            'supplier_country_code': id_paese,
        }

        # --- Body ---
        bodies = data.get('fattura_elettronica_body', [])
        if bodies:
            body = bodies[0]
            dati_gen = body.get('dati_generali', {}).get('dati_generali_documento', {})

            vals['invoice_number'] = dati_gen.get('numero', '')
            vals['invoice_date'] = dati_gen.get('data', False)
            vals['currency_code'] = dati_gen.get('divisa', 'EUR')

            # Importo totale
            total_str = dati_gen.get('importo_totale_documento', '')
            try:
                vals['total_amount'] = float(total_str) if total_str else 0.0
            except (ValueError, TypeError):
                vals['total_amount'] = 0.0

            # Tipo documento (l'AI potrebbe restituirlo o no)
            tipo_doc = dati_gen.get('tipo_documento', '')
            if tipo_doc in dict(self._fields['tipo_documento'].selection):
                vals['tipo_documento'] = tipo_doc

            # --- Righe dettaglio ---
            linee = body.get('dati_beni_servizi', {}).get('dettaglio_linee', [])
            line_vals = []
            for linea in linee:
                line_data = self._parse_detail_line(linea)
                if line_data:
                    line_vals.append((0, 0, line_data))

            # Rimuovi righe esistenti e ricrea
            vals['line_ids'] = [(5, 0, 0)] + line_vals

        self.write(vals)

    def _parse_detail_line(self, linea):
        """Parsa una singola riga DettaglioLinee dal JSON A-Cube."""
        descrizione = linea.get('descrizione', '')
        if not descrizione:
            return None

        def safe_float(value, default=0.0):
            try:
                return float(value) if value else default
            except (ValueError, TypeError):
                return default

        return {
            'description': descrizione,
            'quantity': safe_float(linea.get('quantita'), 1.0),
            'price_unit': safe_float(linea.get('prezzo_unitario')),
            'vat_rate': safe_float(linea.get('aliquota_iva'), 22.0),
        }

    # =====================================================================
    # CREAZIONE FATTURA ODOO
    # =====================================================================

    def action_create_invoice(self):
        """Step 3 → Done: Crea fattura fornitore in bozza dai dati rivisti."""
        self.ensure_one()

        if not self.supplier_name and not self.supplier_vat:
            raise UserError(_(
                "Inserisci almeno la ragione sociale o la P.IVA del fornitore."
            ))

        # 1. Cerca o crea il fornitore
        partner = self._find_or_create_supplier()

        # 2. Prepara le righe fattura
        invoice_lines = []
        for line in self.line_ids:
            tax = self._find_purchase_tax(line.vat_rate)
            line_vals = {
                'name': line.description or '/',
                'quantity': line.quantity,
                'price_unit': line.price_unit,
            }
            if tax:
                line_vals['tax_ids'] = [(6, 0, [tax.id])]
            invoice_lines.append((0, 0, line_vals))

        if not invoice_lines:
            raise UserError(_(
                "Nessuna riga fattura da importare. "
                "Aggiungi almeno una riga prima di creare la fattura."
            ))

        # 3. Crea la fattura fornitore in bozza
        invoice_vals = {
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': self.invoice_date or fields.Date.today(),
            'ref': self.invoice_number or '',
            'acube_source': 'pdf_import',
            'invoice_line_ids': invoice_lines,
        }

        _logger.info(
            "Creazione fattura fornitore da PDF: partner=%s, ref=%s, righe=%d",
            partner.name, self.invoice_number, len(invoice_lines),
        )

        invoice = self.env['account.move'].with_context(
            default_move_type='in_invoice',
        ).create(invoice_vals)

        # 4. Salva il PDF originale come allegato
        if self.pdf_file:
            self.env['ir.attachment'].create({
                'name': self.pdf_filename or 'fattura_originale.pdf',
                'type': 'binary',
                'datas': self.pdf_file,  # già base64
                'res_model': 'account.move',
                'res_id': invoice.id,
                'mimetype': 'application/pdf',
            })

        # 5. Salva l'XML FatturaPA generato come allegato
        if self.extracted_xml:
            xml_filename = (self.pdf_filename or 'fattura').rsplit('.', 1)[0] + '_FatturaPA.xml'
            self.env['ir.attachment'].create({
                'name': xml_filename,
                'type': 'binary',
                'datas': base64.b64encode(self.extracted_xml.encode('utf-8')),
                'res_model': 'account.move',
                'res_id': invoice.id,
                'mimetype': 'application/xml',
            })

        self.write({
            'invoice_id': invoice.id,
            'state': 'done',
        })

        _logger.info("Fattura fornitore creata: %s (id=%d)", invoice.name, invoice.id)

        # Apri la fattura appena creata
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # =====================================================================
    # HELPERS
    # =====================================================================

    def _find_or_create_supplier(self):
        """Cerca il fornitore per VAT o nome. Se non esiste, lo crea."""
        Partner = self.env['res.partner']
        partner = False

        # Cerca per P.IVA
        if self.supplier_vat:
            vat = self.supplier_vat.strip()
            partner = Partner.search([('vat', '=', vat)], limit=1)
            if not partner and len(vat) > 2:
                # Prova senza prefisso paese
                partner = Partner.search([
                    ('vat', 'ilike', vat[2:])
                ], limit=1)

        # Cerca per nome
        if not partner and self.supplier_name:
            partner = Partner.search([
                ('name', 'ilike', self.supplier_name.strip())
            ], limit=1)

        # Crea nuovo fornitore
        if not partner:
            country = False
            if self.supplier_country_code:
                country = self.env['res.country'].search([
                    ('code', '=', self.supplier_country_code.upper())
                ], limit=1)

            partner = Partner.create({
                'name': self.supplier_name or _('Fornitore estero (da completare)'),
                'vat': self.supplier_vat or False,
                'is_company': True,
                'supplier_rank': 1,
                'country_id': country.id if country else False,
            })
            _logger.info(
                "Creato nuovo fornitore: %s (VAT=%s, paese=%s)",
                partner.name, partner.vat, self.supplier_country_code,
            )

        return partner

    def _find_purchase_tax(self, rate):
        """Cerca un'aliquota IVA acquisti nella company corrente per percentuale."""
        if not rate:
            return False

        tax = self.env['account.tax'].search([
            ('type_tax_use', '=', 'purchase'),
            ('amount', '=', rate),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        if not tax:
            # Fallback: cerca l'aliquota più vicina
            tax = self.env['account.tax'].search([
                ('type_tax_use', '=', 'purchase'),
                ('amount_type', '=', 'percent'),
                ('company_id', '=', self.env.company.id),
            ], order='amount', limit=1)
            if tax:
                _logger.warning(
                    "Aliquota IVA %.2f%% non trovata, uso fallback: %s (%.2f%%)",
                    rate, tax.name, tax.amount,
                )

        return tax

    def _reopen_wizard(self):
        """Restituisce l'azione per riaprire il wizard nello stato corrente."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class AcubeImportPdfWizardLine(models.TransientModel):
    _name = 'acube.import.pdf.wizard.line'
    _description = 'Riga fattura estratta da PDF - A-Cube AI'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'acube.import.pdf.wizard',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    description = fields.Char('Descrizione', required=True)
    quantity = fields.Float('Quantità', default=1.0, digits=(16, 4))
    price_unit = fields.Float('Prezzo Unitario', digits=(16, 2))
    vat_rate = fields.Float('Aliquota IVA (%)', default=22.0)
    subtotal = fields.Float(
        'Subtotale',
        compute='_compute_subtotal',
        digits=(16, 2),
    )

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit
