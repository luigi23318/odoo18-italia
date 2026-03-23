import base64
import io
import logging
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ForeignInvoiceBatch(models.Model):
    _name = 'foreign.invoice.batch'
    _description = 'Batch Fatture Estere'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Nome Batch',
        required=True,
        readonly=True,
        default='/',
        copy=False,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Bozza'),
            ('processing', 'In Elaborazione'),
            ('extracted', 'Estratto'),
            ('reviewed', 'Revisionato'),
            ('xml_generated', 'XML Generati'),
            ('sent', 'Inviato'),
            ('done', 'Completato'),
            ('error', 'Errore'),
        ],
        string='Stato',
        default='draft',
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Azienda',
        required=True,
        default=lambda self: self.env.company,
    )
    document_type = fields.Selection(
        selection=[
            ('TD17', 'TD17 - Servizi esteri'),
            ('TD18', 'TD18 - Beni intraUE'),
            ('TD19', 'TD19 - Beni art.17 c.2'),
        ],
        string='Tipo Documento Default',
    )
    import_ids = fields.One2many(
        'foreign.invoice.import',
        'batch_id',
        string='Fatture',
    )
    import_count = fields.Integer(
        string='Numero Fatture',
        compute='_compute_counts',
        store=True,
    )
    error_count = fields.Integer(
        string='Fatture in Errore',
        compute='_compute_counts',
        store=True,
    )
    sent_count = fields.Integer(
        string='Fatture Inviate',
        compute='_compute_counts',
        store=True,
    )
    done_count = fields.Integer(
        string='Fatture Completate',
        compute='_compute_counts',
        store=True,
    )
    notes = fields.Text(
        string='Note',
    )

    @api.depends('import_ids', 'import_ids.state')
    def _compute_counts(self):
        for batch in self:
            imports = batch.import_ids
            batch.import_count = len(imports)
            batch.error_count = len(imports.filtered(lambda r: r.state == 'error'))
            batch.sent_count = len(imports.filtered(lambda r: r.state in ('sent', 'delivered', 'accepted')))
            batch.done_count = len(imports.filtered(lambda r: r.state == 'accepted'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'foreign.invoice.batch'
                ) or '/'
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # AZIONI BATCH
    # -------------------------------------------------------------------------

    def action_extract_all(self):
        """Estrae dati da tutte le fatture del batch."""
        self.ensure_one()
        self.state = 'processing'
        errors = []
        for inv in self.import_ids.filtered(lambda r: r.state == 'draft'):
            try:
                inv.action_extract()
            except Exception as e:
                errors.append(f'{inv.name}: {e}')
                inv.state = 'error'
                inv.sdi_error_message = str(e)
        if not errors:
            self.state = 'extracted'
        else:
            self.state = 'error'
            self.message_post(body=_('Errori estrazione:\n%s') % '\n'.join(errors))
        return True

    def action_generate_all_xml(self):
        """Genera XML per tutte le fatture revisionate nel batch."""
        self.ensure_one()
        errors = []
        for inv in self.import_ids.filtered(lambda r: r.state == 'reviewed'):
            try:
                inv.action_generate_xml()
                inv.action_validate_xml()
            except Exception as e:
                errors.append(f'{inv.name}: {e}')
        if not errors:
            self.state = 'xml_generated'
        else:
            self.message_post(body=_('Errori generazione XML:\n%s') % '\n'.join(errors))
        return True

    def action_send_all_sdi(self):
        """Invia tutte le fatture validate al SDI."""
        self.ensure_one()
        errors = []
        for inv in self.import_ids.filtered(lambda r: r.state == 'xml_validated'):
            try:
                inv.action_send_sdi()
            except Exception as e:
                errors.append(f'{inv.name}: {e}')
        sent = self.import_ids.filtered(lambda r: r.state in ('sent', 'delivered', 'accepted'))
        if sent:
            self.state = 'sent'
        if errors:
            self.message_post(body=_('Errori invio SDI:\n%s') % '\n'.join(errors))
        return True

    def action_check_all_sdi_status(self):
        """Controlla stato SDI di tutte le fatture inviate."""
        self.ensure_one()
        for inv in self.import_ids.filtered(lambda r: r.state == 'sent'):
            try:
                inv.action_check_sdi_status()
            except Exception as e:
                _logger.warning('Errore check SDI %s: %s', inv.name, e)
        # Aggiorna stato batch
        if all(inv.state == 'accepted' for inv in self.import_ids):
            self.state = 'done'
        return True

    def action_download_all_xml(self):
        """Download ZIP con tutti gli XML del batch."""
        self.ensure_one()
        invoices_with_xml = self.import_ids.filtered(lambda r: r.xml_file)
        if not invoices_with_xml:
            raise UserError(_('Nessun XML generato nel batch.'))

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for inv in invoices_with_xml:
                xml_data = base64.b64decode(inv.xml_file)
                zf.writestr(inv.xml_filename or f'{inv.name}.xml', xml_data)

        zip_content = base64.b64encode(zip_buffer.getvalue())
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}_XML.zip',
            'datas': zip_content,
            'type': 'binary',
            'mimetype': 'application/zip',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_view_imports(self):
        """Apri lista fatture del batch."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fatture Batch %s') % self.name,
            'res_model': 'foreign.invoice.import',
            'domain': [('batch_id', '=', self.id)],
            'views': [(False, 'list'), (False, 'form')],
            'context': {'default_batch_id': self.id},
        }

    def action_print_control_report(self):
        """Stampa report di controllo batch."""
        self.ensure_one()
        return self.env.ref(
            'l10n_it_foreign_invoice_sdi.action_report_batch_control'
        ).report_action(self)
