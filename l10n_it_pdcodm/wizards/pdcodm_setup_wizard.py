# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import file_path

_logger = logging.getLogger(__name__)

# Mapping per stima conti per regime (popolato lazily dal CSV statico).
# Ricalcolato a runtime al primo uso per evitare letture sincrone al boot.
_REGIME_COUNT_CACHE = None


def _read_regime_counts():
    """Read the regime distribution from the static CSV bundled with the
    module. Result cached at module level.

    Uso `file_path` (Odoo 18 canonical) per risolvere il path nel
    addons-path corretto; apertura UTF-8 esplicita perché il default
    di `open()` varia per OS.
    """
    global _REGIME_COUNT_CACHE
    if _REGIME_COUNT_CACHE is not None:
        return _REGIME_COUNT_CACHE
    import csv as _csv
    counts = {'azienda_ordinaria': 0, 'professionista': 0,
              'forfetario': 0, 'semplificata': 0, 'storico': 0}
    try:
        path = file_path('l10n_it_pdcodm/data/template/account.account-it_pdcodm.csv')
        with open(path, encoding='utf-8', newline='') as f:
            for row in _csv.DictReader(f):
                regs = {x.strip() for x in (row.get('l10n_it_pdcodm_regime') or '').split(',') if x.strip()}
                for r in regs:
                    if r in counts:
                        counts[r] += 1
    except (FileNotFoundError, ValueError) as e:
        _logger.warning("Impossibile leggere il CSV di template per il preview: %s", e)
    _REGIME_COUNT_CACHE = counts
    return counts


class PdcodmSetupWizard(models.TransientModel):
    """Wizard one-shot per il setup iniziale del PdC OdooManager su
    una company italiana vergine (SPEC 7.1, opzione C semplificata).

    Flusso: 1 schermata di configurazione (con preview live computed),
    bottone "Carica" con conferma, schermata esito.

    L'attivazione del PdC è possibile **solo** su company senza
    scritture contabili (SPEC 5.2). I conti incompatibili con il
    regime scelto vengono deprecati (`deprecated=True`) post-loading.
    """
    _name = 'l10n_it_pdcodm.setup.wizard'
    _description = "Wizard di setup PdC OdooManager"

    company_id = fields.Many2one(
        'res.company',
        string="Azienda",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('form', "Configurazione"),
            ('done', "Caricamento completato"),
        ],
        default='form',
        required=True,
    )

    regime = fields.Selection(
        selection=[
            ('azienda_ordinaria', "Azienda ordinaria (Srl/Spa/Snc/Sas/Ditta individuale)"),
            ('professionista', "Studio professionale (regime di cassa)"),
            ('forfetario', "Regime forfetario"),
            ('semplificata', "Contabilità semplificata"),
        ],
        string="Tipologia azienda",
        required=True,
        default='azienda_ordinaria',
    )

    include_storico = fields.Boolean(
        string="Includi conti storici (Amm.to anticipato)",
        default=False,
        help="Se attivo, lascia attivi anche i conti del regime 'storico' "
             "(ammortamento anticipato, obsoleto dal 2008).",
    )
    strict_mode = fields.Boolean(
        string="Strict mode (controlli stringenti)",
        default=True,
        help="Se attivo, applica i controlli stringenti italiani su causali, "
             "regimi e coerenza CEE (SPEC 6).",
    )
    create_journals = fields.Boolean(
        string="Crea giornali italiani standard",
        default=True,
        help="Se attivo, crea 6 giornali contabili standard "
             "(vendite, acquisti, cassa, banca, operazioni varie, apertura/chiusura).",
    )

    # Preview (computed live al cambio regime/include_storico)
    preview_account_count = fields.Integer(
        string="Conti che saranno attivi",
        compute='_compute_preview',
        readonly=True,
    )
    preview_total_count = fields.Integer(
        string="Conti caricati (totale)",
        compute='_compute_preview',
        readonly=True,
        help="Tutti i 2121 conti del PdC OdooManager vengono caricati; "
             "quelli non compatibili con il regime scelto sono deprecati "
             "(disattivati).",
    )
    preview_deprecated_count = fields.Integer(
        string="Conti deprecati",
        compute='_compute_preview',
        readonly=True,
    )
    preview_estimated_seconds = fields.Integer(
        string="Tempo stimato (secondi)",
        compute='_compute_preview',
        readonly=True,
    )

    # Esito (popolato a fine load, mostrato nello state 'done')
    result_summary = fields.Text(
        string="Esito",
        readonly=True,
    )

    @api.depends('regime', 'include_storico')
    def _compute_preview(self):
        counts = _read_regime_counts()
        total = sum(counts.values())  # NB: somma con overlap, non count univoco
        # Uso il count del regime selezionato come stima della "parte attiva"
        for w in self:
            base = counts.get(w.regime, 0)
            storico = counts.get('storico', 0) if w.include_storico else 0
            w.preview_account_count = base + storico
            w.preview_total_count = 2121  # totale CSV
            w.preview_deprecated_count = w.preview_total_count - w.preview_account_count
            # ~44s per il caricamento completo, indipendente dal regime
            # (Sessione 5: 43.9s misurati). Aggiungiamo margine.
            w.preview_estimated_seconds = 60

    # --- Actions ---

    def _reopen_self(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_load_pdc(self):
        """Esegue il caricamento del PdC OdooManager sulla company.

        1. Validazione precondizioni (no scritture, no PdC già attivo).
        2. Imposta i flag su `res.company`.
        3. Caricamento template via `account.chart.template.try_loading`.
        4. Deprecazione conti non compatibili col regime.
        5. Creazione giornali italiani standard (opzionale).
        6. Log esito + transizione a state='done'.

        Note multi-company:
        - `res.company.write()` funziona anche se `env.company` è
          diversa dalla target: basta che l'utente abbia la target
          nelle proprie `user.company_ids` (cosa garantita per admin
          OdooManager).
        - `try_loading()` forza internamente `allowed_company_ids` alla
          company target (chart_template.py:193-200), quindi tutto
          il caricamento dei 2121 conti avviene nel context corretto.
        - I 2 helper `_deprecate_incompatible_accounts` e
          `_create_italian_journals` usano `.sudo()` internamente, così
          funzionano indipendentemente da `allowed_company_ids` del
          chiamante.
        """
        self.ensure_one()
        company = self.company_id

        # (1) Precondizioni
        move_count = self.env['account.move'].sudo().search_count([
            ('company_id', '=', company.id),
        ])
        if move_count > 0:
            raise UserError(_(
                "L'azienda %(company)s ha già %(count)d scritture contabili. "
                "Il PdC OdooManager può essere attivato solo su aziende vergini."
            ) % {'company': company.name, 'count': move_count})
        if company.l10n_it_pdcodm_enabled:
            raise UserError(_(
                "Il PdC OdooManager è già attivo sull'azienda %(company)s."
            ) % {'company': company.name})

        # Check defensivo: verifica residui orfani del PdC OdooManager.
        # Può capitare se lo stato della company è stato modificato
        # manualmente (via shell, SQL, developer mode) senza usare i
        # wizard, lasciando i conti origin='standard' senza il flag
        # `enabled`. In tal caso, il setup non si può ri-eseguire
        # finché i conti non vengono puliti.
        existing_pdcodm_accounts = self.env['account.account'].sudo().search_count([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_origin', '=', 'standard'),
        ])
        if existing_pdcodm_accounts > 0:
            raise UserError(_(
                "L'azienda %(company)s ha già %(count)d conti del PdC "
                "OdooManager caricati (origin='standard') ma il flag "
                "'Usa PdC OdooManager' è disattivo.\n\n"
                "Lo stato è incoerente — è successo qualcosa di anomalo "
                "(es. modifica diretta via shell/SQL/developer mode).\n\n"
                "Per ripristinare uno stato coerente:\n"
                "  • Se intendi MANTENERE il PdC OdooManager: usa "
                "`odoo shell` per riallineare il flag a True, oppure "
                "modifica res.company.l10n_it_pdcodm_enabled via "
                "developer mode.\n"
                "  • Se intendi RIMUOVERE il PdC: imposta temporaneamente "
                "il flag a True via shell, poi lancia il wizard di "
                "disinstallazione che farà la pulizia completa."
            ) % {'company': company.name, 'count': existing_pdcodm_accounts})

        _logger.info(
            "PdC OdooManager: avvio setup su company '%s' (id=%s), regime=%s, "
            "include_storico=%s, strict_mode=%s, create_journals=%s",
            company.name, company.id, self.regime, self.include_storico,
            self.strict_mode, self.create_journals,
        )

        # (2) Imposta i flag
        company.write({
            'l10n_it_pdcodm_enabled': True,
            'l10n_it_pdcodm_regime': self.regime,
            'l10n_it_pdcodm_strict_mode': self.strict_mode,
            'l10n_it_pdcodm_include_storico': self.include_storico,
        })

        # (3) Caricamento template (~44s)
        # try_loading() imposta da solo allowed_company_ids=[company.id]
        ChartTemplate = self.env['account.chart.template']
        ChartTemplate.try_loading('it_pdcodm', company, install_demo=False)

        # (4) Deprecazione conti non compatibili
        # _deprecate_incompatible_accounts usa .sudo() internamente
        deprecated_count = self._deprecate_incompatible_accounts(company)

        # (5) Giornali standard italiani
        # _create_italian_journals usa .sudo().with_company(company) internamente
        journals_created = 0
        if self.create_journals:
            journals_created = self._create_italian_journals(company)

        # (6) Riassunto + transizione
        summary_lines = [
            _("PdC OdooManager caricato sull'azienda %s.") % company.name,
            _("Regime: %s") % dict(self._fields['regime'].selection).get(self.regime),
            _("Conti deprecati (incompatibili col regime): %d") % deprecated_count,
            _("Giornali italiani creati: %d") % journals_created,
            _("Strict mode: %s") % (self.strict_mode and _("attivo") or _("disattivo")),
        ]
        self.result_summary = '\n'.join(summary_lines)
        self.state = 'done'
        _logger.info("PdC OdooManager: setup completato su company '%s'.", company.name)
        return self._reopen_self()

    def _deprecate_incompatible_accounts(self, company):
        """Marca `deprecated=True` i conti del PdC con regime non
        compatibile con quello della company.

        Ritorna il numero di conti deprecati.

        NB: usa `.sudo()` su entrambe search e write per essere robusto
        a qualsiasi context multi-company del chiamante (l'operazione
        è legittima — parte del flusso di setup PdC).
        """
        regime = company.l10n_it_pdcodm_regime
        include_storico = company.l10n_it_pdcodm_include_storico
        # Tutti i conti caricati dal template (origin='standard') della company
        accounts = self.env['account.account'].sudo().search([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_origin', '=', 'standard'),
        ])
        to_deprecate = self.env['account.account'].sudo()
        for acc in accounts:
            regs = {x.strip() for x in (acc.l10n_it_pdcodm_regime or '').split(',') if x.strip()}
            if regime in regs:
                # Compatibile col regime principale → mantengo
                continue
            if 'storico' in regs and include_storico:
                # Storico richiesto → mantengo
                continue
            to_deprecate |= acc.sudo()
        if to_deprecate:
            to_deprecate.write({'deprecated': True})
        return len(to_deprecate)

    def _create_italian_journals(self, company):
        """Crea 6 giornali contabili italiani standard (SPEC 7.1)."""
        Journal = self.env['account.journal'].sudo().with_company(company)
        journals_data = [
            {'name': "Fatture clienti", 'code': 'VEND', 'type': 'sale'},
            {'name': "Fatture fornitori", 'code': 'ACQ', 'type': 'purchase'},
            {'name': "Cassa", 'code': 'CASSA', 'type': 'cash'},
            {'name': "Banca", 'code': 'BANCA', 'type': 'bank'},
            {'name': "Operazioni varie", 'code': 'OPVAR', 'type': 'general'},
            {'name': "Apertura/Chiusura", 'code': 'APCHI', 'type': 'general'},
        ]
        created = 0
        for jd in journals_data:
            existing = Journal.search([
                ('code', '=', jd['code']),
                ('company_id', '=', company.id),
            ], limit=1)
            if existing:
                continue
            Journal.create(dict(jd, company_id=company.id))
            created += 1
        return created

    def action_close(self):
        """Chiude il wizard a setup completato."""
        return {'type': 'ir.actions.act_window_close'}
