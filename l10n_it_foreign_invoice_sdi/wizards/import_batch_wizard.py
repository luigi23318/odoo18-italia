import base64
import io
import logging
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportBatchWizard(models.TransientModel):
    _name = 'foreign.invoice.import.batch.wizard'
    _description = 'Wizard Importazione Batch Fatture Estere'

    upload_file = fields.Binary(
        string='File ZIP con PDF',
        required=True,
        help='Carica un file ZIP contenente i PDF delle fatture estere.',
    )
    upload_filename = fields.Char(
        string='Nome File',
    )
    document_type = fields.Selection(
        selection=[
            ('TD17', 'TD17 - Servizi esteri'),
            ('TD18', 'TD18 - Beni intraUE'),
            ('TD19', 'TD19 - Beni art.17 c.2'),
        ],
        string='Tipo Documento Default',
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
        default=False,
        help='Se attivo, avvia l\'estrazione subito dopo l\'importazione.',
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
        """Importa PDF da ZIP e crea batch con fatture."""
        self.ensure_one()
        if not self.upload_file:
            raise UserError(_('Seleziona un file ZIP.'))

        zip_data = base64.b64decode(self.upload_file)
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_data))
        except zipfile.BadZipFile:
            raise UserError(_('Il file caricato non è un archivio ZIP valido.'))

        pdf_files = [
            name for name in zf.namelist()
            if name.lower().endswith('.pdf') and not name.startswith('__MACOSX')
        ]

        if not pdf_files:
            raise UserError(_('Nessun file PDF trovato nell\'archivio ZIP.'))

        # Crea batch
        batch = self.env['foreign.invoice.batch'].create({
            'document_type': self.document_type,
        })

        # Crea fatture
        for pdf_name in pdf_files:
            pdf_content = zf.read(pdf_name)
            filename = pdf_name.split('/')[-1]

            self.env['foreign.invoice.import'].create({
                'batch_id': batch.id,
                'document_type': self.document_type,
                'pdf_file': base64.b64encode(pdf_content),
                'pdf_filename': filename,
                'extraction_engine': self.extraction_engine,
            })

        zf.close()

        _logger.info(
            'Batch %s creato con %d fatture da ZIP',
            batch.name, len(pdf_files),
        )

        # Estrazione automatica
        if self.auto_extract:
            batch.action_extract_all()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'foreign.invoice.batch',
            'res_id': batch.id,
            'views': [(False, 'form')],
            'target': 'current',
        }
