# Copyright 2026 Luigi Trubiani - OdooManager.cloud
# License LGPL-3.0

from odoo import _, api, models
from odoo.exceptions import UserError


class L10nItEdiSummaryData(models.Model):
    _inherit = "l10n_it_edi.summary_data"

    # ==================================================================
    # Lock: i summary e-fattura sono read-only sulle fatture cliente
    # Stesse regole di l10n_it_edi.line
    # ==================================================================

    @api.model_create_multi
    def create(self, vals_list):
        self._om_check_customer_invoice_operation(vals_list, operation="create")
        return super().create(vals_list)

    def write(self, vals):
        self._om_check_customer_invoice_operation(self, operation="write")
        return super().write(vals)

    def unlink(self):
        self._om_check_customer_invoice_operation(self, operation="unlink")
        return super().unlink()

    def _om_check_customer_invoice_operation(self, records_or_vals, operation):
        """Blocca operazioni sui summary e-fattura di fatture cliente."""
        if self.env.context.get("om_edi_sync_in_progress"):
            return

        if self.env.su:
            return

        invoice_ids = set()

        if operation == "create":
            for vals in records_or_vals:
                inv_id = vals.get("invoice_id")
                if inv_id:
                    invoice_ids.add(inv_id)
        else:
            invoice_ids = set(records_or_vals.mapped("invoice_id").ids)

        if not invoice_ids:
            return

        customer_invoices = self.env["account.move"].browse(invoice_ids).filtered(
            lambda m: m.move_type in ("out_invoice", "out_refund")
        )

        if customer_invoices:
            raise UserError(
                _(
                    "Il riepilogo del tab 'Dettagli e-fattura' è gestito "
                    "automaticamente dal sistema e non può essere modificato "
                    "manualmente sulle fatture cliente.\n\n"
                    "Per aggiornare questi dati, modifica le righe della "
                    "fattura nel tab 'Righe fattura': il tab 'Dettagli "
                    "e-fattura' si sincronizzerà automaticamente.\n\n"
                    "In alternativa usa il pulsante 'Ricalcola dettagli "
                    "e-fattura' in alto."
                )
            )
