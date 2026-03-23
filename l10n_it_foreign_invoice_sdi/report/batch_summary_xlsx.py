import base64
import io
import logging

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None
    _logger.warning('xlsxwriter non installato. Export XLSX non disponibile.')


class BatchSummaryXlsx(models.AbstractModel):
    _name = 'foreign.invoice.batch.summary.xlsx'
    _description = 'Export XLSX Riepilogo Batch'

    @api.model
    def generate_xlsx(self, batch):
        """Genera file XLSX riepilogativo del batch.

        :param batch: record foreign.invoice.batch
        :returns: tuple (base64_content, filename)
        """
        if not xlsxwriter:
            raise UserError(_('Libreria xlsxwriter non installata.'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Riepilogo')

        # Formati
        header_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1,
        })
        money_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        date_fmt = workbook.add_format({'num_format': 'dd/mm/yyyy', 'border': 1})
        cell_fmt = workbook.add_format({'border': 1})
        total_fmt = workbook.add_format({
            'bold': True,
            'num_format': '#,##0.00',
            'border': 1,
            'bg_color': '#D9E2F3',
        })

        # Intestazione batch
        sheet.write(0, 0, f'Batch: {batch.name}', header_fmt)
        sheet.write(0, 2, f'Stato: {batch.state}')

        # Header colonne
        headers = [
            'Rif.', 'Tipo', 'Fornitore', 'P.IVA', 'Nr. Fattura',
            'Data', 'Imponibile', 'Imposta', 'Totale', 'Stato', 'ID SDI',
        ]
        for col, header in enumerate(headers):
            sheet.write(2, col, header, header_fmt)

        # Dati
        row = 3
        for inv in batch.import_ids:
            sheet.write(row, 0, inv.name or '', cell_fmt)
            sheet.write(row, 1, inv.document_type or '', cell_fmt)
            sheet.write(row, 2, inv.supplier_denomination or '', cell_fmt)
            sheet.write(row, 3, inv.supplier_vat or '', cell_fmt)
            sheet.write(row, 4, inv.invoice_number or '', cell_fmt)
            sheet.write(row, 5, str(inv.invoice_date or ''), date_fmt)
            sheet.write(row, 6, inv.total_untaxed or 0, money_fmt)
            sheet.write(row, 7, inv.total_tax or 0, money_fmt)
            sheet.write(row, 8, inv.total_amount or 0, money_fmt)
            sheet.write(row, 9, inv.state or '', cell_fmt)
            sheet.write(row, 10, inv.sdi_file_id or '', cell_fmt)
            row += 1

        # Riga totali
        sheet.write(row, 5, 'TOTALI', total_fmt)
        for col in (6, 7, 8):
            col_letter = chr(65 + col)
            formula = f'=SUM({col_letter}4:{col_letter}{row})'
            sheet.write_formula(row, col, formula, total_fmt)

        # Larghezza colonne
        widths = [12, 8, 25, 18, 15, 12, 14, 14, 14, 12, 20]
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)

        workbook.close()
        xlsx_data = base64.b64encode(output.getvalue())
        filename = f'{batch.name}_riepilogo.xlsx'
        return xlsx_data, filename
