import base64
import io
import logging

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BatchSummaryXlsx(models.AbstractModel):
    _name = 'report.l10n_it_foreign_invoice_sdi.batch_summary_xlsx'
    _description = 'Export Excel riepilogo batch'

    def _generate_xlsx(self, batch: 'foreign.invoice.batch') -> bytes:
        """Genera file XLSX con 3 fogli."""
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            raise UserError(
                _('Libreria openpyxl non installata. '
                  'Installare: pip install openpyxl')
            )

        wb = openpyxl.Workbook()
        header_font = Font(bold=True, color='FFFFFF')
        header_fill = PatternFill('solid', fgColor='4472C4')

        # Foglio 1: Riepilogo fatture
        ws1 = wb.active
        ws1.title = 'Riepilogo'
        headers_1 = [
            'Rif.', 'Fornitore', 'P.IVA', 'Paese', 'N. fattura',
            'Data fattura', 'Data ricezione', 'TD', 'Imponibile',
            'IVA estera', 'Totale', 'Valuta', 'Stato', 'Template',
        ]
        for col, h in enumerate(headers_1, 1):
            cell = ws1.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill

        for row, inv in enumerate(batch.invoice_ids, 2):
            ws1.cell(row=row, column=1, value=inv.name)
            ws1.cell(row=row, column=2, value=inv.supplier_name or '')
            ws1.cell(row=row, column=3, value=inv.supplier_vat or '')
            ws1.cell(
                row=row, column=4,
                value=inv.supplier_country_id.name if inv.supplier_country_id else '',
            )
            ws1.cell(row=row, column=5, value=inv.invoice_number or '')
            ws1.cell(
                row=row, column=6,
                value=inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else '',
            )
            ws1.cell(
                row=row, column=7,
                value=inv.reception_date.strftime('%d/%m/%Y') if inv.reception_date else '',
            )
            ws1.cell(row=row, column=8, value=inv.tipo_documento or '')
            ws1.cell(row=row, column=9, value=inv.amount_untaxed or 0)
            ws1.cell(row=row, column=10, value=inv.amount_tax_foreign or 0)
            ws1.cell(row=row, column=11, value=inv.amount_total or 0)
            ws1.cell(
                row=row, column=12,
                value=inv.currency_id.name if inv.currency_id else 'EUR',
            )
            ws1.cell(row=row, column=13, value=inv.state or '')
            ws1.cell(
                row=row, column=14,
                value='Sì' if inv.template_matched else 'No',
            )

        # Foglio 2: Righe dettaglio
        ws2 = wb.create_sheet('Righe dettaglio')
        headers_2 = [
            'Rif. fattura', 'Fornitore', 'Descrizione riga',
            'Quantità', 'Prezzo unitario', 'Totale riga', 'IVA estera %',
        ]
        for col, h in enumerate(headers_2, 1):
            cell = ws2.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill

        row = 2
        for inv in batch.invoice_ids:
            for line in inv.line_ids:
                ws2.cell(row=row, column=1, value=inv.name)
                ws2.cell(row=row, column=2, value=inv.supplier_name or '')
                ws2.cell(row=row, column=3, value=line.description or '')
                ws2.cell(row=row, column=4, value=line.quantity or 0)
                ws2.cell(row=row, column=5, value=line.unit_price or 0)
                ws2.cell(row=row, column=6, value=line.line_total or 0)
                ws2.cell(row=row, column=7, value=line.tax_rate_foreign or 0)
                row += 1

        # Foglio 3: Riepilogo IVA
        ws3 = wb.create_sheet('Riepilogo IVA')
        headers_3 = ['TD', 'Aliquota IVA IT', 'Natura', 'N. fatture', 'Imponibile']
        for col, h in enumerate(headers_3, 1):
            cell = ws3.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill

        iva_groups = {}
        for inv in batch.invoice_ids:
            key = (
                inv.tipo_documento or 'N/D',
                inv.it_tax_id.name if inv.it_tax_id else 'N/D',
                inv.natura_code or 'N/D',
            )
            if key not in iva_groups:
                iva_groups[key] = {'count': 0, 'amount': 0}
            iva_groups[key]['count'] += 1
            iva_groups[key]['amount'] += inv.amount_untaxed or 0

        row = 2
        for (td, tax, natura), vals in sorted(iva_groups.items()):
            ws3.cell(row=row, column=1, value=td)
            ws3.cell(row=row, column=2, value=tax)
            ws3.cell(row=row, column=3, value=natura)
            ws3.cell(row=row, column=4, value=vals['count'])
            ws3.cell(row=row, column=5, value=vals['amount'])
            row += 1

        # Auto-width
        for ws in [ws1, ws2, ws3]:
            for col in ws.columns:
                max_len = max(len(str(c.value or '')) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

        buffer = io.BytesIO()
        wb.save(buffer)
        return buffer.getvalue()
