import base64
import io
import logging
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BATCH_STATE_SELECTION = [
    ('bozza', 'Bozza'),
    ('in_elaborazione', 'In elaborazione'),
    ('elaborato', 'Elaborato'),
    ('in_revisione', 'In revisione'),
    ('validato', 'Validato'),
    ('xml_generato', 'XML generato'),
    ('inviato', 'Inviato'),
    ('completato', 'Completato'),
    ('errore', 'Errore'),
]


class ForeignInvoiceBatch(models.Model):
    _name = 'foreign.invoice.batch'
    _description = 'Batch importazione fatture estere'
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    name = fields.Char(
        string='Riferimento',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nuovo'),
    )
    state = fields.Selection(
        selection=BATCH_STATE_SELECTION,
        string='Stato',
        default='bozza',
        required=True,
        tracking=True,
    )

    # Default da applicare
    reception_date_default = fields.Date(
        string='Data ricezione default',
        default=fields.Date.context_today,
    )
    tipo_documento_default = fields.Selection(
        selection=[
            ('TD17', 'TD17 - Servizi'),
            ('TD18', 'TD18 - Beni intracomunitari'),
            ('TD19', 'TD19 - Beni già in Italia'),
        ],
        string='Tipo documento default',
        default='TD17',
    )
    it_tax_id_default = fields.Many2one(
        'account.tax',
        string='Aliquota IVA default',
        domain=[('type_tax_use', '=', 'purchase')],
    )
    natura_code_default = fields.Selection(
        selection=[
            ('N2.1', 'N2.1'), ('N2.2', 'N2.2'),
            ('N3.4', 'N3.4'), ('N3.6', 'N3.6'), ('N4', 'N4'),
        ],
        string='Codice Natura default',
    )

    # Fatture
    invoice_ids = fields.One2many(
        'foreign.invoice.import',
        'batch_id',
        string='Fatture',
    )

    # Computed
    total_invoices = fields.Integer(
        string='Totale fatture', compute='_compute_totals', store=True,
    )
    total_matched = fields.Integer(
        string='Con template', compute='_compute_totals', store=True,
    )
    total_unmatched = fields.Integer(
        string='Senza template', compute='_compute_totals', store=True,
    )
    total_validated = fields.Integer(
        string='Validate', compute='_compute_totals', store=True,
    )
    total_errors = fields.Integer(
        string='Con errori', compute='_compute_totals', store=True,
    )
    total_amount = fields.Float(
        string='Totale importi', compute='_compute_totals', store=True,
        digits=(16, 2),
    )
    total_sent_sdi = fields.Integer(
        string='Inviate SDI', compute='_compute_totals', store=True,
    )
    total_delivered_sdi = fields.Integer(
        string='Consegnate SDI', compute='_compute_totals', store=True,
    )
    total_rejected_sdi = fields.Integer(
        string='Scartate SDI', compute='_compute_totals', store=True,
    )

    @api.depends(
        'invoice_ids', 'invoice_ids.state', 'invoice_ids.amount_total',
        'invoice_ids.template_matched', 'invoice_ids.validation_errors',
    )
    def _compute_totals(self) -> None:
        for batch in self:
            invs = batch.invoice_ids
            batch.total_invoices = len(invs)
            batch.total_matched = len(invs.filtered('template_matched'))
            batch.total_unmatched = len(
                invs.filtered(lambda r: not r.template_matched)
            )
            batch.total_validated = len(
                invs.filtered(lambda r: r.state in (
                    'validato', 'xml_generato', 'inviato_sdi',
                    'consegnato', 'registrato',
                ))
            )
            batch.total_errors = len(
                invs.filtered(lambda r: r.validation_errors)
            )
            batch.total_amount = sum(invs.mapped('amount_total'))
            batch.total_sent_sdi = len(
                invs.filtered(lambda r: r.state == 'inviato_sdi')
            )
            batch.total_delivered_sdi = len(
                invs.filtered(lambda r: r.state == 'consegnato')
            )
            batch.total_rejected_sdi = len(
                invs.filtered(lambda r: r.state == 'scartato')
            )

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> 'ForeignInvoiceBatch':
        for vals in vals_list:
            if vals.get('name', _('Nuovo')) == _('Nuovo'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'foreign.invoice.batch'
                ) or _('Nuovo')
        return super().create(vals_list)

    def action_apply_defaults(self) -> None:
        """Applica i default del batch a tutte le fatture."""
        for batch in self:
            vals = {}
            if batch.reception_date_default:
                vals['reception_date'] = batch.reception_date_default
            if batch.tipo_documento_default:
                vals['tipo_documento'] = batch.tipo_documento_default
            if batch.it_tax_id_default:
                vals['it_tax_id'] = batch.it_tax_id_default.id
            if batch.natura_code_default:
                vals['natura_code'] = batch.natura_code_default
            if vals:
                batch.invoice_ids.write(vals)
            _logger.info(
                'Default applicati a %d fatture nel batch %s',
                len(batch.invoice_ids), batch.name,
            )

    def action_extract_all(self) -> None:
        """Estrae dati da tutti i PDF nel batch."""
        for batch in self:
            batch.state = 'in_elaborazione'
            for inv in batch.invoice_ids.filtered(
                lambda r: r.state == 'bozza'
            ):
                try:
                    inv.action_extract()
                except Exception as e:
                    _logger.exception(
                        'Errore estrazione per %s nel batch %s',
                        inv.name, batch.name,
                    )
                    inv.validation_errors = str(e)
            batch.state = 'elaborato'

    def action_validate_all(self) -> None:
        """Valida tutte le fatture nel batch."""
        for batch in self:
            for inv in batch.invoice_ids.filtered(
                lambda r: r.state in (
                    'dati_estratti', 'nessun_template', 'in_revisione',
                )
            ):
                try:
                    inv.action_validate()
                except UserError:
                    pass  # Errori salvati in validation_errors
            if all(
                r.state == 'validato'
                for r in batch.invoice_ids
            ):
                batch.state = 'validato'
            else:
                batch.state = 'in_revisione'

    def action_generate_all_xml(self) -> None:
        """Genera XML per tutte le fatture validate."""
        for batch in self:
            for inv in batch.invoice_ids.filtered(
                lambda r: r.state == 'validato'
            ):
                try:
                    inv.action_generate_xml()
                except Exception as e:
                    _logger.exception(
                        'Errore generazione XML per %s', inv.name,
                    )
                    inv.validation_errors = str(e)
            if any(
                r.state == 'xml_generato' for r in batch.invoice_ids
            ):
                batch.state = 'xml_generato'

    def action_send_all_sdi(self) -> None:
        """Invia tutti gli XML allo SDI."""
        for batch in self:
            for inv in batch.invoice_ids.filtered(
                lambda r: r.state == 'xml_generato'
            ):
                try:
                    inv.action_send_sdi()
                except Exception as e:
                    _logger.exception(
                        'Errore invio SDI per %s', inv.name,
                    )
                    inv.validation_errors = str(e)
            if any(
                r.state == 'inviato_sdi' for r in batch.invoice_ids
            ):
                batch.state = 'inviato'

    def action_download_zip_xml(self) -> dict:
        """Genera e scarica ZIP con tutti gli XML del batch."""
        self.ensure_one()
        xml_invoices = self.invoice_ids.filtered(
            lambda r: r.xml_attachment_id
        )
        if not xml_invoices:
            raise UserError(_('Nessun XML generato nel batch.'))

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for inv in xml_invoices:
                att = inv.xml_attachment_id
                zf.writestr(
                    att.name,
                    base64.b64decode(att.datas),
                )

        zip_data = base64.b64encode(buffer.getvalue())
        zip_name = f'{self.name}_XML.zip'
        attachment = self.env['ir.attachment'].create({
            'name': zip_name,
            'type': 'binary',
            'datas': zip_data,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/zip',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def action_register_all_accounting(self) -> None:
        """Registra tutte le fatture consegnate."""
        for batch in self:
            for inv in batch.invoice_ids.filtered(
                lambda r: r.state in (
                    'consegnato', 'xml_generato', 'inviato_sdi',
                ) and not r.account_move_id
            ):
                try:
                    inv.action_register_accounting()
                except Exception as e:
                    _logger.exception(
                        'Errore registrazione contabile per %s', inv.name,
                    )
                    inv.validation_errors = str(e)
            batch.state = 'completato'

    def action_print_control_report(self) -> dict:
        """Stampa report PDF controllo batch."""
        return self.env.ref(
            'l10n_it_foreign_invoice_sdi.action_report_batch_control'
        ).report_action(self)

    def action_export_xlsx(self) -> dict:
        """Genera e scarica Excel riepilogo batch."""
        self.ensure_one()
        report = self.env[
            'report.l10n_it_foreign_invoice_sdi.batch_summary_xlsx'
        ]
        xlsx_data = report._generate_xlsx(self)
        xlsx_name = f'{self.name}_Riepilogo.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': xlsx_name,
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': (
                'application/vnd.openxmlformats-officedocument'
                '.spreadsheetml.sheet'
            ),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
