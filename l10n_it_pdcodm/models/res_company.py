# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    """Estensione di res.company con il flag di attivazione del PdC
    OdooManager e relativa configurazione fiscale.

    Vedi SPEC sezione 4.3 e 5 (logica di attivazione e lock).
    """
    _inherit = 'res.company'

    l10n_it_pdcodm_enabled = fields.Boolean(
        string="Usa PdC OdooManager",
        default=False,
        help="Se attivo, questa azienda utilizza il Piano dei Conti italiano "
             "professionale OdooManager. L'attivazione è permessa solo su "
             "aziende che non hanno ancora scritture contabili.",
    )
    l10n_it_pdcodm_regime = fields.Selection(
        selection=[
            ('azienda_ordinaria', "Azienda ordinaria (Srl/Spa/Snc/Sas/Ditta individuale)"),
            ('professionista', "Studio professionale (regime di cassa)"),
            ('forfetario', "Regime forfetario"),
            ('semplificata', "Contabilità semplificata"),
        ],
        string="Regime fiscale",
        default='azienda_ordinaria',
        help="Regime fiscale dell'azienda. Determina quali conti del PdC sono "
             "visibili e utilizzabili (controllo C, SPEC 6.2).",
    )
    l10n_it_pdcodm_locked = fields.Boolean(
        string="PdC bloccato (azienda operativa)",
        compute='_compute_pdcodm_locked',
        store=True,
        help="Se True, l'azienda ha già scritture contabili e il PdC è in "
             "modalità operativa permanente: il setup contabile non è più "
             "modificabile (SPEC 5.4-5.5).",
    )
    l10n_it_pdcodm_locked_date = fields.Datetime(
        string="Data lock PdC",
        readonly=True,
        help="Data e ora in cui il PdC è stato bloccato in modalità "
             "operativa (prima scrittura contabile).",
    )
    l10n_it_pdcodm_strict_mode = fields.Boolean(
        string="Strict mode (controlli stringenti)",
        default=True,
        help="Se True, applica i controlli stringenti italiani su causali, "
             "regimi e coerenza CEE (SPEC 6).",
    )
    l10n_it_pdcodm_include_storico = fields.Boolean(
        string="Includi conti storici (Amm.to anticipato)",
        default=False,
        help="Scelta del wizard di SETUP iniziale: se True, i conti del "
             "regime 'storico' (ammortamento anticipato, obsoleto dal 2008) "
             "vengono lasciati attivi al caricamento del PdC. Se False, "
             "vengono marcati come `deprecated`. "
             "DOPO il setup questo flag è readonly: i conti già attivi o "
             "deprecati non vengono riconfigurati cambiando il flag — "
             "modificarlo non avrebbe effetto pratico.",
    )

    # Campi sensibili che NON possono essere modificati su company lockata
    # (SPEC 5.5). I nomi reali dei campi su `res.company` in Odoo 18 base:
    # chart_template (Selection), currency_id (M2O), country_id (M2O).
    # `account_fiscal_country_id` proviene dal modulo `account` (presente,
    # dato che `l10n_it_pdcodm` dipende da `account`).
    _PDCODM_LOCKED_FIELDS = (
        'l10n_it_pdcodm_enabled',
        'l10n_it_pdcodm_regime',
        'chart_template',
        'currency_id',
        'country_id',
        'account_fiscal_country_id',
    )

    @api.depends('l10n_it_pdcodm_enabled')
    def _compute_pdcodm_locked(self):
        """Calcola se il PdC è bloccato.

        Definizione di "locked": la company ha **almeno una scrittura
        contabile CONFERMATA** (state='posted'). Le bozze e gli annullati
        NON bloccano: un utente che ha postato per errore può tornare
        indietro (button_draft → cancel/unlink) e il lock si scioglie
        automaticamente.

        Trigger esterni del recompute (override in models/account_move.py):
        - `_post()` → quando si conferma una scrittura, il lock può scattare
        - `button_draft()` → quando si annulla una conferma, il lock può
          sciogliersi
        - `unlink()` → quando si elimina una scrittura, idem

        Il `@api.depends` qui resta minimal (solo `l10n_it_pdcodm_enabled`)
        perché un depends fine su `account.move.state` provocherebbe
        ricompute massivi a ogni modifica di scrittura per qualsiasi
        company del DB.
        """
        for company in self:
            if not company.l10n_it_pdcodm_enabled:
                company.l10n_it_pdcodm_locked = False
                company.l10n_it_pdcodm_locked_date = False
                continue
            move_count = self.env['account.move'].sudo().search_count([
                ('company_id', '=', company.id),
                ('state', '=', 'posted'),
            ])
            was_locked = company.l10n_it_pdcodm_locked
            new_locked = move_count > 0
            company.l10n_it_pdcodm_locked = new_locked
            if new_locked and not was_locked:
                # Lock appena scattato: registro la data corrente
                company.l10n_it_pdcodm_locked_date = fields.Datetime.now()
                _logger.info(
                    "PdC OdooManager: company '%s' (id=%s) entrata in "
                    "modalità lock (%d scritture confermate).",
                    company.name, company.id, move_count,
                )
            elif was_locked and not new_locked:
                # Lock appena sciolto (tutte le scritture posted sono
                # tornate a draft/cancelled/unlink): reset della data
                company.l10n_it_pdcodm_locked_date = False
                _logger.info(
                    "PdC OdooManager: company '%s' (id=%s) uscita dalla "
                    "modalità lock (nessuna scrittura confermata residua).",
                    company.name, company.id,
                )

    @api.constrains('l10n_it_pdcodm_enabled', 'chart_template')
    def _check_pdcodm_required_chart_template(self):
        """Controllo E (SPEC 6.3 adattato per Odoo 18).

        Se il PdC OdooManager è attivo su una company, allora la
        company DEVE avere chart_template impostato. La SPEC 6.3
        prescriveva di verificare `property_account_receivable_id` e
        `property_account_payable_id` come campi su company, ma in
        Odoo 18 queste property vivono su `res.partner` con
        `company_dependent=True` (non direttamente sulla company).

        Il setting di `chart_template` da parte di `try_loading` è
        un indicatore equivalente: significa che il template è stato
        caricato correttamente, e le property accounts sono state
        registrate dal template stesso.
        """
        for company in self:
            if not company.l10n_it_pdcodm_enabled:
                continue
            if not company.chart_template:
                raise ValidationError(_(
                    "L'azienda %(company)s ha il PdC OdooManager attivo "
                    "ma non ha alcun chart template impostato.\n\n"
                    "Lo stato è incoerente. Lancia il wizard \"Configura "
                    "PdC OdooManager\" per ricaricare i conti, oppure "
                    "(per recovery) usa `odoo shell` per resettare lo "
                    "stato manualmente."
                ) % {'company': company.name})

    def action_open_pdcodm_setup_wizard(self):
        """Apre il wizard di setup PdC OdooManager per questa company.

        Pattern Odoo 18: il bottone della view chiama un metodo
        `type="object"` (server-side), evitando l'ambiguità del pattern
        `type="action" name="%(action_id)d"` che in certe form non
        salvate richiede un doppio click per attivarsi.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Configura PdC OdooManager"),
            'res_model': 'l10n_it_pdcodm.setup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_company_id': self.id},
        }

    def action_open_pdcodm_uninstall_wizard(self):
        """Apre il wizard di disinstallazione PdC OdooManager.

        Permette solo a company vergini (no scritture). Pattern
        `type="object"` per coerenza con setup_wizard.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Disinstalla PdC OdooManager"),
            'res_model': 'l10n_it_pdcodm.uninstall.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_company_id': self.id},
        }

    def _recompute_pdcodm_locked(self):
        """API pubblica usata in Sessione 8 da `account.move._post()`
        per forzare il recompute del lock alla prima scrittura.

        Non chiamato in Sessione 4 — definito qui come placeholder
        documentato perché lo userà la sessione 8.
        """
        # `_compute_pdcodm_locked` è già `depends` su `enabled`; un
        # invalidate + recompute esplicito basta.
        self.invalidate_recordset(['l10n_it_pdcodm_locked'])
        for company in self:
            company._compute_pdcodm_locked()

    def write(self, vals):
        """Override per:
        a. Bloccare attivazione (False → True) se l'azienda ha scritture
           (SPEC 5.2).
        b. Bloccare disattivazione (True → False) se ci sono scritture
           su conti origin='standard' (SPEC 5.3).
        c. Bloccare modifica di campi sensibili su company lockata
           (SPEC 5.5).
        """
        # (a) e (b): check sul flag `l10n_it_pdcodm_enabled`
        if 'l10n_it_pdcodm_enabled' in vals:
            new_value = vals['l10n_it_pdcodm_enabled']
            for company in self:
                if new_value and not company.l10n_it_pdcodm_enabled:
                    # Transizione False → True: blocca se ci sono scritture
                    move_count = self.env['account.move'].sudo().search_count([
                        ('company_id', '=', company.id),
                    ])
                    if move_count > 0:
                        raise UserError(_(
                            "Impossibile attivare il PdC OdooManager "
                            "sull'azienda %(company)s.\n\n"
                            "Sono presenti %(count)d scritture contabili "
                            "(in bozza o confermate) registrate nel sistema.\n\n"
                            "Il PdC OdooManager può essere attivato solo su "
                            "aziende non ancora utilizzate. Crea una nuova "
                            "azienda e attiva il modulo all'inizio."
                        ) % {'company': company.name, 'count': move_count})
                elif not new_value and company.l10n_it_pdcodm_enabled:
                    # Transizione True → False: blocca se ci sono scritture
                    # CONFERMATE (state='posted') su conti origin='standard'.
                    # Le bozze NON bloccano: l'utente può annullarle/eliminarle
                    # prima di disattivare il PdC.
                    move_count = self.env['account.move'].sudo().search_count([
                        ('company_id', '=', company.id),
                        ('state', '=', 'posted'),
                        ('line_ids.account_id.l10n_it_pdcodm_origin', '=', 'standard'),
                    ])
                    if move_count > 0:
                        raise UserError(_(
                            "Impossibile disattivare il PdC OdooManager "
                            "sull'azienda %(company)s.\n\n"
                            "Sono presenti %(count)d scritture su conti del "
                            "Piano dei Conti OdooManager. Il PdC è permanente: "
                            "una volta avviata la contabilità, non è più "
                            "possibile cambiarlo.\n\n"
                            "Per migrare a un altro PdC, crea una nuova azienda."
                        ) % {'company': company.name, 'count': move_count})

        # (c): check sui LOCKED_FIELDS su company lockata
        intersect = set(self._PDCODM_LOCKED_FIELDS) & set(vals.keys())
        if intersect:
            for company in self:
                if company.l10n_it_pdcodm_locked:
                    # Se solo `l10n_it_pdcodm_locked_date` cambia
                    # (impostato dal compute), non bloccare.
                    raise UserError(_(
                        "Impossibile modificare i campi %(fields)s "
                        "sull'azienda %(company)s con PdC OdooManager "
                        "operativo.\n\n"
                        "Il PdC è bloccato per garantire l'integrità "
                        "contabile delle scritture già registrate."
                    ) % {
                        'fields': ', '.join(sorted(intersect)),
                        'company': company.name,
                    })

        return super().write(vals)
