import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ForeignInvoiceImportSingleWizard(models.TransientModel):
    _name = 'foreign.invoice.import.single.wizard'
    _description = 'Wizard importazione singola fattura estera da PDF'

    pdf_file = fields.Binary(string='File PDF', required=True)
    pdf_filename = fields.Char(string='Nome file')
    reception_date = fields.Date(
        string='Data ricezione',
        default=fields.Date.context_today,
        required=True,
    )
    auto_extract = fields.Boolean(
        string='Estrai automaticamente', default=True,
    )

    def action_import(self) -> dict:
        """Importa il PDF e crea il record fattura estera."""
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_('Selezionare un file PDF.'))

        attachment = self.env['ir.attachment'].create({
            'name': self.pdf_filename or 'fattura.pdf',
            'type': 'binary',
            'datas': self.pdf_file,
            'mimetype': 'application/pdf',
        })

        invoice = self.env['foreign.invoice.import'].create({
            'pdf_attachment_id': attachment.id,
            'reception_date': self.reception_date,
        })

        attachment.write({
            'res_model': 'foreign.invoice.import',
            'res_id': invoice.id,
        })

        ICP = self.env['ir.config_parameter'].sudo()
        auto_extract = ICP.get_param(
            'foreign_invoice.auto_extract', 'True',
        )
        if self.auto_extract and auto_extract in ('True', 'true', '1', True):
            try:
                invoice.action_extract()
            except Exception as e:
                _logger.exception(
                    'Errore auto-estrazione per %s', invoice.name,
                )
                invoice.validation_errors = str(e)

        _logger.info(
            'Fattura estera importata: %s da %s',
            invoice.name, self.pdf_filename,
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'foreign.invoice.import',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }
