from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ImportSingleWizard(models.TransientModel):
    _name = 'foreign.invoice.import.single.wizard'
    _description = 'Wizard Importazione Singola Fattura Estera'

    pdf_file = fields.Binary(
        string='File PDF Fattura',
        required=True,
    )
    pdf_filename = fields.Char(
        string='Nome File',
    )
    document_type = fields.Selection(
        selection=[
            ('TD17', 'TD17 - Servizi esteri'),
            ('TD18', 'TD18 - Beni intraUE'),
            ('TD19', 'TD19 - Beni art.17 c.2'),
        ],
        string='Tipo Documento',
        required=True,
        default='TD17',
    )
    extraction_engine = fields.Selection(
        selection=[
            ('tesseract', 'Tesseract OCR (Locale)'),
            ('acube', 'A-Cube API (Cloud)'),
        ],
        string='Motore Estrazione',
    )
    auto_extract = fields.Boolean(
        string='Estrai dati automaticamente',
        default=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ICP = self.env['ir.config_parameter'].sudo()
        res['extraction_engine'] = ICP.get_param(
            'l10n_it_foreign_invoice_sdi.default_extraction_engine', 'tesseract'
        )
        return res

    def action_import(self):
        """Crea la fattura estera dal PDF caricato."""
        self.ensure_one()
        if not self.pdf_file:
            raise UserError(_('Seleziona un file PDF.'))

        invoice = self.env['foreign.invoice.import'].create({
            'document_type': self.document_type,
            'pdf_file': self.pdf_file,
            'pdf_filename': self.pdf_filename,
            'extraction_engine': self.extraction_engine,
        })

        if self.auto_extract:
            invoice.action_extract()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'foreign.invoice.import',
            'res_id': invoice.id,
            'views': [(False, 'form')],
            'target': 'current',
        }
