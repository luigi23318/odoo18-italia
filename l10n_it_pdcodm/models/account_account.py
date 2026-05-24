# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountAccount(models.Model):
    """Estensione del piano dei conti con metadati italiani.

    Aggiunge 6 campi italiani (CEE, deducibilità IRES/IRAP, regime,
    origine) come da SPEC sezione 4.1. I campi sono trackati nel
    chatter (`mail.thread`) per audit log — SPEC 6.4 punto G.

    Implementa anche i constraint CRUD della SPEC 8.2 e 8.3:
    - `unlink`: blocca su `origin='standard'`, blocca su `'user'`
      usati in scritture. Bypass via context `l10n_it_pdcodm_force_unlink`.
    - `write`: blocca `code/account_type/origin` su `'standard'`,
      blocca `reconcile` su conti già usati. Bypass via context
      `l10n_it_pdcodm_force_write`.
    """
    _inherit = 'account.account'

    # Campi readonly su conti origin='standard' (SPEC 8.3).
    # `name` è incluso perché modificarlo retroattivamente rompe la
    # ristampa identica dei bilanci di esercizi chiusi: in Odoo il
    # template del report legge il valore CORRENTE del campo, non
    # quello storico al momento della scrittura. Compliance contabile
    # italiana richiede ristampabilità immutabile dei bilanci passati.
    # L'utente che vuole personalizzare la descrizione di un conto deve
    # duplicare il conto come `origin='user'` (wizard "Duplica conto"),
    # poi disattivare lo standard via `deprecated=True` se non lo usa.
    _PDCODM_READONLY_ON_STANDARD = ('code', 'name', 'account_type', 'l10n_it_pdcodm_origin')

    l10n_it_pdcodm_cee_code = fields.Char(
        string="Codice CEE",
        size=20,
        index=True,
        tracking=True,
        help="Codice voce CEE per riclassificazione del bilancio civilistico "
             "(artt. 2424/2425 c.c.). L'elenco delle voci è consultabile dal "
             "menu 'Piano dei Conti OdooManager → Voci CEE'.",
    )
    l10n_it_pdcodm_cee_section_id = fields.Many2one(
        comodel_name='l10n_it_pdcodm.cee.section',
        string="Voce CEE",
        compute='_compute_cee_section',
        store=True,
        tracking=True,
        help="Riferimento alla voce CEE associata, calcolato automaticamente "
             "dal codice CEE.",
    )
    l10n_it_pdcodm_cee_code_dare = fields.Char(
        string="Codice CEE (saldo DARE)",
        size=20,
        tracking=True,
        help="Codice CEE da usare nell'export bilancio Passepartout quando "
             "il saldo del conto è di tipo DARE (attivo o costo). "
             "Lasciare vuoto per usare il `Codice CEE` principale. "
             "Popolare solo sui conti 'misti' che possono avere CEE diverso "
             "a seconda del segno del saldo (es. Banca: dare=CIV1, avere=D4).",
    )
    l10n_it_pdcodm_cee_code_avere = fields.Char(
        string="Codice CEE (saldo AVERE)",
        size=20,
        tracking=True,
        help="Codice CEE da usare nell'export bilancio Passepartout quando "
             "il saldo del conto è di tipo AVERE (passivo o ricavo). "
             "Lasciare vuoto per usare il `Codice CEE` principale. "
             "Popolare solo sui conti 'misti' che possono avere CEE diverso "
             "a seconda del segno del saldo.",
    )
    l10n_it_pdcodm_ires_deductibility = fields.Float(
        string="Deducibilità IRES (%)",
        default=0.0,
        tracking=True,
        help="Percentuale di deducibilità ai fini IRES come da TUIR. "
             "100 = pienamente deducibile.",
    )
    l10n_it_pdcodm_irap_deductibility = fields.Float(
        string="Deducibilità IRAP (%)",
        default=0.0,
        tracking=True,
        help="Percentuale di deducibilità ai fini IRAP come da D.Lgs. 446/1997.",
    )
    l10n_it_pdcodm_regime = fields.Char(
        string="Regimi applicabili",
        size=200,
        tracking=True,
        help="Elenco CSV dei regimi fiscali che possono usare questo conto: "
             "azienda_ordinaria, professionista, forfetario, semplificata, "
             "storico. Vuoto = universale (compatibile con tutti i regimi).",
    )
    l10n_it_pdcodm_origin = fields.Selection(
        selection=[
            ('standard', "PdC OdooManager (standard)"),
            ('user', "Creato dall'utente"),
            ('external', "Conto esterno (es. l10n_it standard)"),
        ],
        string="Origine conto",
        default='external',
        tracking=True,
        help="Origine del conto contabile. Determina i permessi di "
             "modifica/eliminazione (vedi SPEC 8.1 — matrice permessi).",
    )

    @api.depends('l10n_it_pdcodm_cee_code')
    def _compute_cee_section(self):
        """Risolvi il riferimento alla voce CEE in base al codice testuale.

        Search semplice: 1 query per record nel caso peggiore. Per gli
        update di massa (es. caricamento chart template) è accettabile
        — il PdC standard ha ~2100 conti, caricato una volta sola.
        """
        Section = self.env['l10n_it_pdcodm.cee.section']
        for account in self:
            code = account.l10n_it_pdcodm_cee_code
            if code:
                account.l10n_it_pdcodm_cee_section_id = Section.search(
                    [('code', '=', code)], limit=1
                )
            else:
                account.l10n_it_pdcodm_cee_section_id = False

    # ---------------------------------------------------------------
    # CRUD overrides (SPEC 8.2, 8.3)
    # ---------------------------------------------------------------

    def write(self, vals):
        """Blocca modifiche a campi readonly su conti standard
        (`code`, `account_type`, `l10n_it_pdcodm_origin`) e blocca
        `reconcile` su conti già usati in scritture.

        Bypass: `self.env.context.get('l10n_it_pdcodm_force_write')`
        (per uso interno, es. correzione di emergenza).
        """
        if self.env.context.get('l10n_it_pdcodm_force_write'):
            return super().write(vals)

        readonly_intersect = set(self._PDCODM_READONLY_ON_STANDARD) & set(vals.keys())
        check_reconcile = 'reconcile' in vals

        for account in self:
            # Check campi readonly su conti standard
            if readonly_intersect and account.l10n_it_pdcodm_origin == 'standard':
                # Filtra le chiavi che effettivamente cambiano (evita
                # falsi positivi quando il valore è uguale a quello attuale)
                actual_changes = {
                    k for k in readonly_intersect
                    if vals[k] != account[k]
                }
                if actual_changes:
                    raise UserError(_(
                        "Impossibile modificare i campi %(fields)s sul "
                        "conto %(code)s — %(name)s.\n\n"
                        "Si tratta di un conto del Piano dei Conti "
                        "OdooManager standard, e questi campi sono "
                        "immutabili per garantire la coerenza contabile. "
                        "Per esigenze particolari, duplica il conto come "
                        "conto utente dal wizard \"Duplica conto\"."
                    ) % {
                        'fields': ', '.join(sorted(actual_changes)),
                        'code': account.code,
                        'name': account.name,
                    })

            # Check `reconcile` su conto già usato
            if check_reconcile and vals['reconcile'] != account.reconcile:
                used = self.env['account.move.line'].sudo().search_count([
                    ('account_id', '=', account.id),
                ])
                if used > 0:
                    raise UserError(_(
                        "Impossibile cambiare il flag \"Permetti "
                        "riconciliazione\" sul conto %(code)s — %(name)s "
                        "perché è già usato in %(count)d righe di scrittura."
                    ) % {
                        'code': account.code,
                        'name': account.name,
                        'count': used,
                    })

        return super().write(vals)

    def unlink(self):
        """Blocca eliminazione di conti origin='standard' (vanno
        deprecati con `deprecated=True`, non eliminati), e di conti
        origin='user' usati in scritture (vanno deprecati).

        Bypass: `self.env.context.get('l10n_it_pdcodm_force_unlink')`
        (usato dal wizard di disinstallazione PdC — Sessione 7).
        """
        if self.env.context.get('l10n_it_pdcodm_force_unlink'):
            return super().unlink()

        for account in self:
            if account.l10n_it_pdcodm_origin == 'standard':
                raise UserError(_(
                    "Impossibile eliminare il conto %(code)s — %(name)s "
                    "(origine: standard del PdC OdooManager).\n\n"
                    "I conti del PdC standard non sono eliminabili: per "
                    "renderli non utilizzabili, usa la disattivazione "
                    "(flag \"Deprecated\")."
                ) % {'code': account.code, 'name': account.name})
            if account.l10n_it_pdcodm_origin == 'user':
                used = self.env['account.move.line'].sudo().search_count([
                    ('account_id', '=', account.id),
                ])
                if used > 0:
                    raise UserError(_(
                        "Impossibile eliminare il conto %(code)s — %(name)s "
                        "perché è già usato in %(count)d righe di scrittura.\n\n"
                        "Usa la disattivazione (flag \"Deprecated\") per "
                        "renderlo non più utilizzabile in scritture future."
                    ) % {
                        'code': account.code,
                        'name': account.name,
                        'count': used,
                    })

        return super().unlink()
