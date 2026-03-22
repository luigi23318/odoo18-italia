from datetime import date, timedelta

from odoo import api, models

try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    relativedelta = None


class BatchControlReport(models.AbstractModel):
    _name = 'report.l10n_it_foreign_invoice_sdi.batch_control_report'
    _description = 'Report controllo batch fatture estere'

    @api.model
    def _get_report_values(self, docids, data=None) -> dict:
        batches = self.env['foreign.invoice.batch'].browse(docids)
        warnings = []

        for batch in batches:
            for inv in batch.invoice_ids:
                # Incoerenze matematiche
                if inv.line_ids:
                    line_sum = sum(inv.line_ids.mapped('line_total'))
                    if (
                        inv.amount_untaxed
                        and abs(line_sum - inv.amount_untaxed) > 0.01
                    ):
                        warnings.append({
                            'invoice': inv.name,
                            'type': 'math',
                            'message': (
                                f'Somma righe ({line_sum:.2f}) diversa '
                                f'da imponibile ({inv.amount_untaxed:.2f})'
                            ),
                        })

                # P.IVA non trovata in Odoo
                if inv.supplier_vat and not inv.partner_id:
                    warnings.append({
                        'invoice': inv.name,
                        'type': 'partner',
                        'message': (
                            f'P.IVA {inv.supplier_vat} non trovata '
                            f'in anagrafica'
                        ),
                    })

                # Scadenza esterometro
                if inv.reception_date and inv.tipo_documento:
                    if (
                        inv.tipo_documento in ('TD17', 'TD18')
                        and relativedelta
                    ):
                        deadline = (
                            inv.reception_date.replace(day=1)
                            + relativedelta(months=1)
                            + timedelta(days=14)
                        )
                    else:
                        deadline = inv.reception_date + timedelta(days=12)

                    if date.today() > deadline:
                        warnings.append({
                            'invoice': inv.name,
                            'type': 'deadline',
                            'message': (
                                f'Scadenza esterometro superata '
                                f'({deadline.strftime("%d/%m/%Y")})'
                            ),
                        })

                # Errori di validazione
                if inv.validation_errors:
                    warnings.append({
                        'invoice': inv.name,
                        'type': 'validation',
                        'message': inv.validation_errors,
                    })

        # Distribuzione per TD e paese
        td_dist = {}
        country_dist = {}
        for batch in batches:
            for inv in batch.invoice_ids:
                td = inv.tipo_documento or 'N/D'
                td_dist[td] = td_dist.get(td, 0) + 1
                country = (
                    inv.supplier_country_id.name
                    if inv.supplier_country_id else 'N/D'
                )
                country_dist[country] = country_dist.get(country, 0) + 1

        return {
            'doc_ids': docids,
            'doc_model': 'foreign.invoice.batch',
            'docs': batches,
            'warnings': warnings,
            'td_distribution': td_dist,
            'country_distribution': country_dist,
        }
