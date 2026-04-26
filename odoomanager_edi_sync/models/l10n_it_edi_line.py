# Copyright 2026 Luigi Trubiani - OdooManager.cloud
# License LGPL-3.0

from odoo import _, api, models
from odoo.exceptions import UserError


class L10nItEdiLine(models.Model):
    _inherit = "l10n_it_edi.line"

    # ==================================================================
    # Lock: le righe e-fattura sono read-only sulle fatture cliente
    # ==================================================================
    # I record vengono creati/modificati/eliminati SOLO dal metodo di
    # sync del nostro modulo, che opera con context flag
    # om_edi_sync_in_progress=True.
    #
    # Sulle fatture passive (in_invoice, in_refund) le operazioni sono
    # consentite per preservare compatibilità con import XML.
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
        """Blocca operazioni su righe e-fattura di fatture cliente, tranne
        quando scatenate dal nostro sync interno.
        """
        # Se siamo dentro il nostro sync, via libera
        if self.env.context.get("om_edi_sync_in_progress"):
            return

        # Superuser bypass per migrazioni/install (es. -i, -u)
        if self.env.su:
            return

        # Identifica le fatture coinvolte
        invoice_ids = set()

        if operation == "create":
            # records_or_vals è vals_list (lista di dict)
            for vals in records_or_vals:
                inv_id = vals.get("invoice_id")
                if inv_id:
                    invoice_ids.add(inv_id)
        else:
            # records_or_vals è un recordset self
            invoice_ids = set(records_or_vals.mapped("invoice_id").ids)

        if not invoice_ids:
            return

        # Cerca fatture cliente tra gli invoice_ids
        customer_invoices = self.env["account.move"].browse(invoice_ids).filtered(
            lambda m: m.move_type in ("out_invoice", "out_refund")
        )

        if customer_invoices:
            raise UserError(
                _(
                    "Le righe del tab 'Dettagli e-fattura' sono gestite "
                    "automaticamente dal sistema e non possono essere "
                    "modificate manualmente sulle fatture cliente.\n\n"
                    "Per aggiornare questi dati, modifica le righe della "
                    "fattura nel tab 'Righe fattura': il tab 'Dettagli "
                    "e-fattura' si sincronizzerà automaticamente.\n\n"
                    "In alternativa usa il pulsante 'Ricalcola dettagli "
                    "e-fattura' in alto."
                )
            )
