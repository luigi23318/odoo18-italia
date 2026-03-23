from odoo import api, models


class BatchControlReport(models.AbstractModel):
    _name = 'report.l10n_it_foreign_invoice_sdi.report_batch_control'
    _description = 'Report Controllo Batch Fatture Estere'

    @api.model
    def _get_report_values(self, docids, data=None):
        batches = self.env['foreign.invoice.batch'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'foreign.invoice.batch',
            'docs': batches,
            'data': data,
        }
