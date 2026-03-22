import base64
import io
import logging
import zipfile

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ForeignInvoiceImportBatchWizard(models.TransientModel):
    _name = 'foreign.invoice.import.batch.wizard'
    _description = 'Wizard importazione batch fatture estere da PDF'

    pdf_files = fields.Many2many(
        'ir.attachment',
        string='File PDF',
        help='Selezionare uno o più file PDF, oppure un file ZIP contenente PDF.',
    )
    zip_file = fields.Binary(string='File ZIP')
    zip_filename = fields.Char(string='Nome file ZIP')
    reception_date = fields.Date(
        string='Data ricezione default',
        default=fields.Date.context_today,
        required=True,
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
    auto_extract = fields.Boolean(
        string='Estrai automaticamente', default=True,
    )

    def action_import(self) -> dict:
        """Importa i PDF e crea il batch."""
        self.ensure_one()

        attachments = self.env['ir.attachment']

        if self.zip_file:
            attachments |= self._extract_zip()

        if self.pdf_files:
            attachments |= self.pdf_files

        if not attachments:
            raise UserError(
                _('Selezionare almeno un file PDF o un file ZIP.')
            )

        batch = self.env['foreign.invoice.batch'].create({
            'reception_date_default': self.reception_date,
            'tipo_documento_default': self.tipo_documento_default,
        })

        for att in attachments:
            invoice = self.env['foreign.invoice.import'].create({
                'pdf_attachment_id': att.id,
                'reception_date': self.reception_date,
                'tipo_documento': self.tipo_documento_default,
                'batch_id': batch.id,
            })
            att.write({
                'res_model': 'foreign.invoice.import',
                'res_id': invoice.id,
            })

        _logger.info(
            'Batch %s creato con %d fatture', batch.name, len(attachments),
        )

        if self.auto_extract:
            batch.action_extract_all()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'foreign.invoice.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _extract_zip(self) -> 'ir.attachment':
        """Estrae PDF da un file ZIP."""
        attachments = self.env['ir.attachment']
        try:
            zip_content = base64.b64decode(self.zip_file)
            with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
                for name in zf.namelist():
                    if (
                        name.lower().endswith('.pdf')
                        and not name.startswith('__')
                    ):
                        pdf_data = zf.read(name)
                        att = self.env['ir.attachment'].create({
                            'name': name.split('/')[-1],
                            'type': 'binary',
                            'datas': base64.b64encode(pdf_data),
                            'mimetype': 'application/pdf',
                        })
                        attachments |= att
        except zipfile.BadZipFile:
            raise UserError(_('Il file ZIP non è valido.'))

        _logger.info('Estratti %d PDF dal file ZIP', len(attachments))
        return attachments
