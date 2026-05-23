# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
#
# Chart template "it_pdcodm" — registrazione e configurazione property.
#
# Pattern Odoo 17/18 (NB: la SPEC 3.2.1 e 7.1 sono scritte con pattern
# Odoo 16 ormai obsoleto. Vedi project_l10n_it_pdcodm_status.md per la
# discrepanza). Il sistema funziona così:
#
# 1. Il modulo deve avere `category` = "Accounting/Localizations/Account Charts"
#    (già impostato in __manifest__.py Sessione 1).
# 2. Questo file DEVE chiamarsi `template_*.py` per essere scoperto da
#    `account.ir_module._compute_account_templates()`.
# 3. La classe deve ereditare `account.chart.template` (AbstractModel).
# 4. La funzione decorata `@template('it_pdcodm')` ritorna un dict
#    con i metadata del template + property accounts.
# 5. La funzione `@template('it_pdcodm', 'res.company')` ritorna un
#    dict con i campi da popolare su `res.company` al caricamento.
# 6. I dati di massa (2121 conti, 69 gruppi) vivono in
#    `data/template/<model>-it_pdcodm.csv` e NON vengono caricati dal
#    manifest: vengono installati on-demand da
#    `account.chart.template.try_loading('it_pdcodm', company)`.
#
from odoo import models
from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('it_pdcodm')
    def _get_it_pdcodm_template_data(self):
        """Metadata del template + 4 property accounts standard
        (SPEC 3.1.4, ridotti ai 4 standard).

        I 9 mapping della SPEC 3.1.4 sono distribuiti così:
        - 4 in `template_data` (questo dict): receivable, payable,
          income_categ, expense_categ;
        - 2 come prefissi su `res.company`: bank_account_code_prefix,
          cash_account_code_prefix (vedi `_get_it_pdcodm_res_company`);
        - 1 (unaffected_earnings) viene risolto automaticamente da
          Odoo 18 cercando il conto con `account_type='equity_unaffected'`
          (qui: codice 308001, già taggato correttamente nel CSV).
        - 2 (account_tax_input, account_tax_output) NON sono campi
          property standard: si configurano dentro alle `account.tax`
          di l10n_it; fuori scope per Sessione 5.

        I 2 mapping custom della SPEC 3.1.4 (`l10n_it_pdcodm_withholding_*`)
        richiedono nuovi campi M2O su `res.company` o estensione del modello
        — implementazione spostata a una sessione futura quando arriverà
        l'integrazione con `l10n_it_withholding_tax`.

        `sequence: 99` ad arte alta: evita che Odoo selezioni
        `it_pdcodm` come auto-default per company con `country_id=IT`
        (rispettando il flusso "wizard di setup" della Sessione 6).
        """
        return {
            'name': "Italia — Piano dei Conti OdooManager (Professional)",
            'code_digits': '6',
            'sequence': 99,
            'visible': True,
            'property_account_receivable_id': 'account_150012',
            'property_account_payable_id': 'account_250004',
            'property_account_income_categ_id': 'account_700002',
            'property_account_expense_categ_id': 'account_600001',
        }

    @template('it_pdcodm', 'res.company')
    def _get_it_pdcodm_res_company(self):
        """Campi da popolare su `res.company` al caricamento del
        template (SPEC 3.1.4, parte company-level).

        - `account_fiscal_country_id`: Italia, riusato da l10n_it.
        - `bank_account_code_prefix='180'`: i journal banca creati
          dopo il caricamento avranno conti `180001, 180002, ...`.
          Il conto 180001 ('Banca') è già nel PdC.
        - `cash_account_code_prefix='182'`: idem per cassa
          (182001 = 'Cassa').
        """
        return {
            self.env.company.id: {
                'account_fiscal_country_id': 'base.it',
                'bank_account_code_prefix': '180',
                'cash_account_code_prefix': '182',
            },
        }
