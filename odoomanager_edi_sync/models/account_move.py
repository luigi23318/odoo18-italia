# Copyright 2026 Luigi Trubiani - OdooManager.cloud
# License LGPL-3.0

from collections import defaultdict

from odoo import _, api, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    # ==================================================================
    # MECCANISMO 1 — Automatico: override create/write
    # ==================================================================
    # A differenza di @api.onchange (che dà problemi con .create() su
    # sub-record), l'override di write/create lavora su record salvati
    # reali, evitando conflitti NewId vs Id.
    #
    # Il sync scatta al salvataggio della fattura:
    # - Sempre al create di una nuova fattura cliente in bozza
    # - Al write quando cambiano invoice_line_ids
    # ==================================================================

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)

        # Sync automatico solo per fatture cliente italiane in bozza
        if not self.env.context.get("om_edi_sync_in_progress"):
            for move in moves.filtered(
                lambda m: m.move_type in ("out_invoice", "out_refund")
                and m.state == "draft"
                and m.country_code == "IT"
            ):
                move.with_context(
                    om_edi_sync_in_progress=True
                )._om_sync_edi_details_silent()

        return moves

    def write(self, vals):
        result = super().write(vals)

        # Sync solo se sono cambiate le righe della fattura
        # (evita ricalcoli inutili per modifiche a campi irrilevanti)
        if (
            "invoice_line_ids" in vals
            and not self.env.context.get("om_edi_sync_in_progress")
        ):
            for move in self.filtered(
                lambda m: m.move_type in ("out_invoice", "out_refund")
                and m.state == "draft"
                and m.country_code == "IT"
            ):
                move.with_context(
                    om_edi_sync_in_progress=True
                )._om_sync_edi_details_silent()

        return result

    # ==================================================================
    # MECCANISMO 2 — Automatico: override di _post() alla conferma
    # ==================================================================

    def _post(self, soft=True):
        """Riallinea il tab e-fattura prima della conferma fattura."""
        for move in self.filtered(
            lambda m: m.move_type in ("out_invoice", "out_refund")
            and m.state == "draft"
            and m.country_code == "IT"
        ):
            move.with_context(
                om_edi_sync_in_progress=True
            )._om_sync_edi_details_silent()

        return super()._post(soft=soft)

    # ==================================================================
    # MECCANISMO 3 — Manuale: pulsante
    # ==================================================================

    def action_om_sync_edi_details(self):
        """Azione utente: ricalcola il tab e-fattura e mostra notifica."""
        for move in self:
            move._om_check_sync_allowed()
            move.with_context(
                om_edi_sync_in_progress=True
            )._om_sync_edi_details_silent()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Dettagli e-fattura aggiornati"),
                "message": _(
                    "Il tab 'Dettagli e-fattura' è stato sincronizzato "
                    "con le righe attuali della fattura."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    # ==================================================================
    # Metodo core — Esegue il ricalcolo
    # ==================================================================

    def _om_sync_edi_details_silent(self):
        """Esegue il ricalcolo. Deve essere chiamato con context
        om_edi_sync_in_progress=True per bypassare il lock tabelle.
        """
        for move in self:
            move._om_recompute_edi_amounts()
            move._om_rebuild_edi_lines()
            move._om_rebuild_edi_summary()

    # ==================================================================
    # Safety check (solo pulsante manuale)
    # ==================================================================

    def _om_check_sync_allowed(self):
        """Verifica prerequisiti per ricalcolo manuale."""
        self.ensure_one()

        if self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(
                _(
                    "Il ricalcolo dettagli e-fattura è disponibile solo per "
                    "fatture cliente. Le fatture fornitore mantengono i valori "
                    "letti dall'XML ricevuto dal canale SDI."
                )
            )

        if self.state == "posted":
            raise UserError(
                _(
                    "Impossibile ricalcolare i dettagli e-fattura su una "
                    "fattura già confermata. Riporta la fattura in bozza "
                    "(pulsante 'Reimposta a bozza') se necessario."
                )
            )

        if self.state == "cancel":
            raise UserError(
                _("Impossibile ricalcolare i dettagli di una fattura annullata.")
            )

    # ==================================================================
    # Step 1 — Ricalcolo totali e-fattura
    # ==================================================================

    def _om_recompute_edi_amounts(self):
        """Ricalcola l10n_it_edi_amount_untaxed e l10n_it_edi_amount_tax."""
        self.ensure_one()
        product_lines = self._om_get_product_lines()

        untaxed = 0.0
        tax_total = 0.0

        for line in product_lines:
            untaxed += line.price_subtotal
            iva_taxes = self._om_filter_iva_taxes(line.tax_ids)
            if iva_taxes:
                iva_rate_total = sum(iva_taxes.mapped("amount"))
                tax_total += line.price_subtotal * iva_rate_total / 100.0

        self.l10n_it_edi_amount_untaxed = untaxed
        self.l10n_it_edi_amount_tax = tax_total

    # ==================================================================
    # Step 2 — Ricostruzione righe e-fattura
    # ==================================================================

    def _om_rebuild_edi_lines(self):
        """Ricrea l10n_it_edi_line_ids: 1 riga per ogni riga prodotto."""
        self.ensure_one()

        self.l10n_it_edi_line_ids.unlink()

        product_lines = self._om_get_product_lines()

        line_vals = []
        for idx, line in enumerate(product_lines, start=1):
            rate, nature = self._om_extract_tax_info(line)

            line_vals.append(
                {
                    "invoice_id": self.id,
                    "invoice_line_id": line.id,
                    "line_number": idx,
                    "name": line.name or (
                        line.product_id.display_name if line.product_id else ""
                    ),
                    "qty": line.quantity,
                    "uom": line.product_uom_id.name if line.product_uom_id else "",
                    "unit_price": line.price_unit,
                    "total_price": line.price_subtotal,
                    "tax_amount": rate,
                    "tax_kind": nature or "",
                }
            )

        if line_vals:
            self.env["l10n_it_edi.line"].create(line_vals)

    # ==================================================================
    # Step 3 — Ricostruzione summary
    # ==================================================================

    def _om_rebuild_edi_summary(self):
        """Ricrea l10n_it_edi_summary_ids aggregando per (aliquota, natura)."""
        self.ensure_one()

        self.l10n_it_edi_summary_ids.unlink()

        product_lines = self._om_get_product_lines()

        grouped = defaultdict(
            lambda: {"untaxed": 0.0, "tax": 0.0, "law_reference": ""}
        )

        for line in product_lines:
            rate, nature = self._om_extract_tax_info(line)
            law_ref = self._om_extract_law_reference(line)
            key = (rate, nature or False)

            grouped[key]["untaxed"] += line.price_subtotal
            grouped[key]["tax"] += line.price_subtotal * rate / 100.0
            if law_ref and not grouped[key]["law_reference"]:
                grouped[key]["law_reference"] = law_ref

        summary_vals = []
        for (rate, nature), amounts in grouped.items():
            summary_vals.append(
                {
                    "invoice_id": self.id,
                    "tax_rate": rate,
                    "non_taxable_nature": nature or False,
                    "amount_untaxed": amounts["untaxed"],
                    "amount_tax": amounts["tax"],
                    "incidental_charges": 0.0,
                    "rounding": 0.0,
                    "law_reference": (amounts["law_reference"] or "")[:128],
                }
            )

        if summary_vals:
            self.env["l10n_it_edi.summary_data"].create(summary_vals)

    # ==================================================================
    # Helpers
    # ==================================================================

    def _om_get_product_lines(self):
        """Restituisce solo righe prodotto."""
        self.ensure_one()
        return self.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
        )

    def _om_filter_iva_taxes(self, taxes):
        """Filtra solo imposte IVA vere (esclude cassa previdenza e ritenute)."""
        return taxes.filtered(
            lambda t: t.l10n_it_exempt_reason
            or (t.amount > 0 and t.amount_type == "percent")
        )

    def _om_extract_tax_info(self, line):
        """Estrae (aliquota, natura) dalla prima imposta IVA della riga."""
        self.ensure_one()
        iva_taxes = self._om_filter_iva_taxes(line.tax_ids)
        if not iva_taxes:
            return (0.0, False)
        first_tax = iva_taxes[0]
        return (first_tax.amount, first_tax.l10n_it_exempt_reason or False)

    def _om_extract_law_reference(self, line):
        """Estrae il riferimento normativo dalla prima imposta IVA della riga."""
        self.ensure_one()
        iva_taxes = self._om_filter_iva_taxes(line.tax_ids)
        if not iva_taxes:
            return ""
        return iva_taxes[0].l10n_it_law_reference or ""
