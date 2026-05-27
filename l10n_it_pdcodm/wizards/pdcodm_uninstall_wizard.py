# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PdcodmUninstallWizard(models.TransientModel):
    """Wizard di disinstallazione PdC OdooManager (SPEC 7.2).

    Permette di disattivare il PdC OdooManager su una company **vergine**
    (senza scritture contabili). Rimuove i conti origin='standard',
    pulisce le property accounts, disattiva il flag, e opzionalmente
    carica il PdC `l10n_it` standard al suo posto.

    Operazione bloccata se la company ha già scritture contabili
    (anche bozza): la SPEC 5.3 garantisce l'immutabilità del PdC
    sulle company operative.
    """
    _name = 'l10n_it_pdcodm.uninstall.wizard'
    _description = "Wizard di disinstallazione PdC OdooManager"

    company_id = fields.Many2one(
        'res.company',
        string="Azienda",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('form', "Conferma"),
            ('done', "Disinstallazione completata"),
        ],
        default='form',
        required=True,
    )

    move_count = fields.Integer(
        string="Scritture contabili presenti",
        compute='_compute_move_count',
        readonly=True,
    )
    account_count = fields.Integer(
        string="Conti standard OdooManager da rimuovere",
        compute='_compute_account_count',
        readonly=True,
    )
    journal_count = fields.Integer(
        string="Giornali della company da rimuovere",
        compute='_compute_journal_count',
        readonly=True,
    )

    result_summary = fields.Text(
        string="Esito",
        readonly=True,
    )

    @api.depends('company_id')
    def _compute_move_count(self):
        # Contiamo TUTTE le scritture esistenti sulla company,
        # indipendentemente dallo state (draft, posted, cancel).
        # Anche le scritture annullate (state='cancel') contengono
        # account.move.line che referenziano i conti del PdC: senza
        # il loro unlink, le FK constraint impediscono di eliminare
        # i conti del PdC, lasciando 2121 conti orfani come fallback
        # `deprecated=True`. Per pulizia totale, blocchiamo finché
        # NON esiste alcuna scrittura sulla company (qualsiasi state).
        for w in self:
            w.move_count = self.env['account.move'].sudo().search_count([
                ('company_id', '=', w.company_id.id),
            ])

    @api.depends('company_id')
    def _compute_account_count(self):
        for w in self:
            w.account_count = self.env['account.account'].sudo().search_count([
                ('company_ids', 'in', w.company_id.id),
                ('l10n_it_pdcodm_origin', '=', 'standard'),
            ])

    @api.depends('company_id')
    def _compute_journal_count(self):
        # active_test=False per includere anche i giornali archiviati
        # dal setup wizard (es. l10n_it residui disattivati con
        # `active=False`). In fase di uninstall vogliamo rimuovere
        # TUTTI i giornali della company, non solo quelli attivi.
        for w in self:
            w.journal_count = self.env['account.journal'].sudo().with_context(
                active_test=False,
            ).search_count([
                ('company_id', '=', w.company_id.id),
            ])

    def _reopen_self(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        """Esegue la disinstallazione del PdC OdooManager.

        L'azienda viene SEMPRE ripristinata al PdC `l10n_it` standard
        (188 conti italiani). Lasciare la company "senza PdC" non è
        un'opzione: un'azienda italiana operativa ha sempre bisogno
        di un piano dei conti — l10n_it è il default Odoo, sempre
        accettabile come base.

        Ordine ottimizzato per evitare IntegrityError sull'unlink:
        1. Validazione: company vergine (zero scritture).
        2. Pulizia property accounts della company (reset a False).
        3. Unlink dei giornali della company (creati dal setup wizard).
        4. `try_loading('it', company)` PRIMA dell'unlink dei conti.
           Riassegna le property esterne (es.
           `product.category.property_account_expense_categ_id`) ai
           conti l10n_it, liberando i conti OdooManager dai riferimenti.
        5. Unlink dei conti origin='standard' (con context di bypass
           del constraint Sessione 9). Fallback a deprecated=True.
        6. Disattivazione del flag PdC + reset configurazione.
        """
        self.ensure_one()
        company = self.company_id

        # (1) Validazione
        if self.move_count > 0:
            raise UserError(_(
                "Impossibile disinstallare il PdC OdooManager "
                "sull'azienda %(company)s.\n\n"
                "Sono presenti %(count)d scritture contabili sulla company "
                "(in qualunque stato: bozza, confermate o annullate).\n\n"
                "Tutte le scritture (incluse le annullate) referenziano "
                "i conti del PdC OdooManager. La loro presenza impedisce "
                "l'eliminazione pulita dei conti.\n\n"
                "Cosa fare:\n"
                "  • Per scritture confermate: riportarle a bozza, poi eliminarle.\n"
                "  • Per scritture in bozza o annullate: eliminarle direttamente.\n"
                "  • Se la contabilità è già operativa, NON cancellare le "
                "scritture — crea invece una nuova azienda con il PdC che preferisci."
            ) % {'company': company.name, 'count': self.move_count})

        if not company.l10n_it_pdcodm_enabled:
            raise UserError(_(
                "Il PdC OdooManager non è attivo sull'azienda %(company)s."
            ) % {'company': company.name})

        _logger.info(
            "PdC OdooManager: avvio disinstallazione su company '%s' "
            "(id=%s); conti=%d, giornali=%d, ripristino l10n_it standard",
            company.name, company.id,
            self.account_count, self.journal_count,
        )

        # (2) Pulizia property accounts della company che puntano a
        # conti OdooManager.
        PROPERTY_FIELDS = [
            'account_default_pos_receivable_account_id',
            'income_currency_exchange_account_id',
            'expense_currency_exchange_account_id',
            'account_journal_early_pay_discount_loss_account_id',
            'account_journal_early_pay_discount_gain_account_id',
            'account_journal_suspense_account_id',
            'default_cash_difference_income_account_id',
            'default_cash_difference_expense_account_id',
            'expense_accrual_account_id',
            'revenue_accrual_account_id',
            'transfer_account_id',
        ]
        reset_vals = {}
        for fname in PROPERTY_FIELDS:
            if fname in company._fields:
                value = company[fname]
                if value and getattr(value, 'l10n_it_pdcodm_origin', None) == 'standard':
                    reset_vals[fname] = False
        if reset_vals:
            company.sudo().write(reset_vals)

        # (3) Unlink dei giornali della company.
        # active_test=False per includere anche i giornali archiviati
        # dal setup wizard (es. l10n_it residui disattivati). Devono
        # essere rimossi anche loro per lasciare la company pulita.
        journals = self.env['account.journal'].sudo().with_context(
            active_test=False,
        ).search([
            ('company_id', '=', company.id),
        ])
        # Snapshot dettagliato PRIMA dell'unlink (dopo, i record sono
        # eliminati e non leggibili). Serve per il summary finale.
        journal_type_labels = {
            'sale': _("vendite"),
            'purchase': _("acquisti"),
            'cash': _("cassa"),
            'bank': _("banca"),
            'general': _("operazioni varie"),
        }
        journals_removed_detail = [{
            'code': j.code,
            'name': j.name,
            'type': journal_type_labels.get(j.type, j.type),
        } for j in journals]
        journals_removed = len(journals)
        if journals:
            try:
                journals.unlink()
            except Exception as e:
                _logger.warning(
                    "PdC OdooManager: impossibile rimuovere %d giornali "
                    "della company %s: %s. Procedo lo stesso.",
                    len(journals), company.name, e,
                )
                journals_removed = 0
                journals_removed_detail = []

        # (4) try_loading('it') PRIMA dell'unlink dei conti
        # Questo riassegna property esterne (product.category, ecc.) al
        # nuovo template, liberando i conti OdooManager dai riferimenti.
        # Reset chart_template per permettere try_loading senza conflitti.
        # NB: setto SIMULTANEAMENTE enabled=False per non triggerare il
        # controllo E (_check_pdcodm_required_chart_template) durante lo
        # stato intermedio "enabled=True + chart_template=False".
        company.sudo().write({
            'chart_template': False,
            'l10n_it_pdcodm_enabled': False,
        })
        ChartTemplate = self.env['account.chart.template']
        l10n_it_loaded = False
        l10n_it_journals_detail = []
        try:
            ChartTemplate.try_loading('it', company, install_demo=False)
            l10n_it_loaded = True
            # Cattura i giornali ricreati dal template l10n_it per
            # mostrarli nel summary (in genere 7: vendite, acquisti,
            # cassa, banca, generale, fatture vendite, fatture acquisti).
            recreated = self.env['account.journal'].sudo().search([
                ('company_id', '=', company.id),
            ])
            l10n_it_journals_detail = [{
                'code': j.code,
                'name': j.name,
                'type': journal_type_labels.get(j.type, j.type),
            } for j in recreated]
        except Exception as e:
            _logger.error(
                "PdC OdooManager: impossibile caricare l10n_it standard "
                "su company %s: %s", company.name, e,
            )

        # (5) Unlink dei conti origin='standard' della company
        accounts = self.env['account.account'].sudo().search([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_origin', '=', 'standard'),
        ])
        accounts_removed = len(accounts)
        if accounts:
            try:
                # Bypass del constraint unlink della Sessione 9 (futura)
                accounts.with_context(l10n_it_pdcodm_force_unlink=True).unlink()
            except Exception as e:
                _logger.warning(
                    "PdC OdooManager: impossibile rimuovere %d conti "
                    "standard della company %s: %s. Fallback: deprecazione.",
                    len(accounts), company.name, e,
                )
                accounts.write({'deprecated': True})
                accounts_removed = 0

        # (6) Disattiva flag + reset configurazione (chart_template è
        # stato già impostato da try_loading('it'); se è fallito, lo
        # resettiamo a False per evitare uno stato incoerente)
        reset_company_vals = {
            'l10n_it_pdcodm_enabled': False,
            'l10n_it_pdcodm_regime': 'azienda_ordinaria',
            'l10n_it_pdcodm_strict_mode': True,
            'l10n_it_pdcodm_include_storico': False,
            'l10n_it_pdcodm_locked_date': False,
        }
        if not l10n_it_loaded:
            reset_company_vals['chart_template'] = False
        company.sudo().write(reset_company_vals)

        # Riassunto
        summary_lines = [
            _("PdC OdooManager disinstallato dall'azienda %s.") % company.name,
            _("Conti standard rimossi: %d") % accounts_removed,
            "",
            _("Giornali rimossi: %d") % journals_removed,
        ]
        for jd in journals_removed_detail:
            summary_lines.append(_("  • [%(code)s] %(name)s (%(type)s)") % jd)

        if l10n_it_loaded:
            summary_lines.append("")
            summary_lines.append(_("PdC `l10n_it` standard caricato con successo."))
            if l10n_it_journals_detail:
                summary_lines.append(
                    _("Giornali ricreati dal PdC l10n_it: %d") % len(l10n_it_journals_detail)
                )
                for jd in l10n_it_journals_detail:
                    summary_lines.append(_("  • [%(code)s] %(name)s (%(type)s)") % jd)
        else:
            summary_lines.append("")
            summary_lines.append(_("ATTENZIONE: caricamento PdC `l10n_it` fallito (vedi log)."))

        self.result_summary = '\n'.join(summary_lines)
        self.state = 'done'
        _logger.info(
            "PdC OdooManager: disinstallazione completata su company '%s'.",
            company.name,
        )
        return self._reopen_self()

    def action_close(self):
        """Chiude il wizard a disinstallazione completata."""
        return {'type': 'ir.actions.act_window_close'}
