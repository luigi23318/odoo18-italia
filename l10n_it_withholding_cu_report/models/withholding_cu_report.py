# Copyright 2026 OdooManager.cloud
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models, tools


class L10nItWithholdingCuReport(models.Model):
    """Vista SQL read-only: una riga per ogni ritenuta realizzata per cassa.

    Sorgente: le righe "imposta" (tax_line_id = ritenuta) delle scritture
    *Tax Cash Basis* generate al pagamento/incasso, sul conto definitivo.
    L'imponibile viene recuperato dalle righe-base della stessa scrittura,
    collegate alla ritenuta via account_move_line_account_tax_rel.
    Nessun dato persistito: è una semplice proiezione su account_move_line.
    """

    _name = "l10n.it.withholding.cu.report"
    _description = "Ritenute per percipiente (dettaglio CU)"
    _auto = False
    _rec_name = "partner_id"
    _order = "date desc, partner_id"

    date = fields.Date(string="Data", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Percipiente", readonly=True)
    tax_id = fields.Many2one("account.tax", string="Ritenuta / Causale", readonly=True)
    withholding_type = fields.Char(string="Cod. ritenuta", readonly=True)
    direction = fields.Selection(
        [("sale", "Subita (vendita)"), ("purchase", "Operata (acquisto)")],
        string="Direzione",
        readonly=True,
    )
    account_id = fields.Many2one(
        "account.account", string="Conto definitivo", readonly=True
    )
    move_id = fields.Many2one(
        "account.move", string="Registrazione cassa", readonly=True
    )
    origin_move_id = fields.Many2one(
        "account.move", string="Fattura origine", readonly=True
    )
    company_id = fields.Many2one("res.company", string="Azienda", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Valuta", readonly=True)
    base_amount = fields.Monetary(
        string="Imponibile", readonly=True, currency_field="currency_id"
    )
    withholding_amount = fields.Monetary(
        string="Ritenuta", readonly=True, currency_field="currency_id"
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    aml.id                              AS id,
                    aml.date                            AS date,
                    aml.partner_id                      AS partner_id,
                    aml.tax_line_id                     AS tax_id,
                    t.l10n_it_withholding_type          AS withholding_type,
                    t.type_tax_use                      AS direction,
                    aml.account_id                      AS account_id,
                    aml.move_id                         AS move_id,
                    cbm.tax_cash_basis_origin_move_id   AS origin_move_id,
                    aml.company_id                      AS company_id,
                    cmp.currency_id                     AS currency_id,
                    (aml.debit + aml.credit)            AS withholding_amount,
                    COALESCE(base.base_amount, 0.0)     AS base_amount
                FROM account_move_line aml
                JOIN account_move cbm
                    ON cbm.id = aml.move_id
                    AND cbm.tax_cash_basis_origin_move_id IS NOT NULL
                JOIN account_tax t
                    ON t.id = aml.tax_line_id
                    AND t.l10n_it_withholding_type IS NOT NULL
                JOIN res_company cmp
                    ON cmp.id = aml.company_id
                LEFT JOIN LATERAL (
                    SELECT SUM(bl.debit + bl.credit) AS base_amount
                    FROM account_move_line bl
                    JOIN account_move_line_account_tax_rel r
                        ON r.account_move_line_id = bl.id
                    WHERE bl.move_id = aml.move_id
                      AND r.account_tax_id = aml.tax_line_id
                      AND bl.tax_line_id IS NULL
                ) base ON TRUE
                WHERE aml.parent_state = 'posted'
            )
            """
            % (self._table,)
        )
