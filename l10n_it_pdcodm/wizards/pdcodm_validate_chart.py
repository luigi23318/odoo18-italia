# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
from collections import Counter

from odoo import _, fields, models


class PdcodmValidateChartWizard(models.TransientModel):
    """Wizard "Validazione coerenza PdC" (SPEC 7.5).

    Esegue diversi check di integrità sul PdC OdooManager della
    company corrente e produce un report testuale delle anomalie
    rilevate.
    """
    _name = 'l10n_it_pdcodm.validate.chart.wizard'
    _description = "Wizard validazione PdC OdooManager"

    state = fields.Selection(
        selection=[
            ('form', "Pronto"),
            ('done', "Esito validazione"),
        ],
        default='form',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string="Azienda",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    issues = fields.Text(
        string="Anomalie rilevate",
        readonly=True,
    )

    def _reopen_self(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_validate(self):
        """Esegue tutti i check e popola il campo `issues`."""
        self.ensure_one()
        company = self.company_id
        Account = self.env['account.account'].sudo()
        Section = self.env['l10n_it_pdcodm.cee.section'].sudo()
        issues = []

        if not company.l10n_it_pdcodm_enabled:
            self.issues = _(
                "L'azienda %s non ha il PdC OdooManager attivo. "
                "Nessuna validazione da eseguire."
            ) % company.name
            self.state = 'done'
            return self._reopen_self()

        # Check 1: chart_template impostato
        if not company.chart_template:
            issues.append(_(
                "[Critico] L'azienda ha enabled=True ma chart_template "
                "non impostato. Stato incoerente: lancia il wizard di setup."
            ))

        # Check 2: conti standard senza codice CEE
        no_cee = Account.search([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_origin', '=', 'standard'),
            ('l10n_it_pdcodm_cee_code', '=', False),
        ])
        if no_cee:
            sample = ', '.join(no_cee[:5].mapped('code'))
            issues.append(_(
                "[Avviso] %(n)d conti standard senza codice CEE "
                "(es: %(sample)s). La riclassificazione di bilancio sarà "
                "incompleta su questi conti."
            ) % {'n': len(no_cee), 'sample': sample})

        # Check 3: codici CEE non esistenti nel modello voci CEE
        existing_cee_codes = set(Section.search([]).mapped('code'))
        accts_with_cee = Account.search([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_cee_code', '!=', False),
        ])
        invalid_cee = accts_with_cee.filtered(
            lambda a: a.l10n_it_pdcodm_cee_code not in existing_cee_codes
        )
        if invalid_cee:
            sample = ', '.join(
                "%s→%s" % (a.code, a.l10n_it_pdcodm_cee_code)
                for a in invalid_cee[:5]
            )
            issues.append(_(
                "[Avviso] %(n)d conti hanno codice CEE non presente nel "
                "modello voci CEE (es: %(sample)s)."
            ) % {'n': len(invalid_cee), 'sample': sample})

        # Check 4: codici duplicati per azienda
        all_accts = Account.search([('company_ids', 'in', company.id)])
        counter = Counter(all_accts.mapped('code'))
        duplicates = {code: n for code, n in counter.items() if n > 1}
        if duplicates:
            sample = ', '.join(
                "%s (%dx)" % (c, n) for c, n in list(duplicates.items())[:5]
            )
            issues.append(_(
                "[Critico] %(n)d codici di conto duplicati "
                "(es: %(sample)s)."
            ) % {'n': len(duplicates), 'sample': sample})

        # Check 5: deducibilità fuori range 0-100
        out_range = Account.search([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_origin', '=', 'standard'),
            '|',
            ('l10n_it_pdcodm_ires_deductibility', '<', 0),
            ('l10n_it_pdcodm_ires_deductibility', '>', 100),
        ]) | Account.search([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_origin', '=', 'standard'),
            '|',
            ('l10n_it_pdcodm_irap_deductibility', '<', 0),
            ('l10n_it_pdcodm_irap_deductibility', '>', 100),
        ])
        if out_range:
            sample = ', '.join(out_range[:5].mapped('code'))
            issues.append(_(
                "[Avviso] %(n)d conti con percentuale di deducibilità "
                "fuori range 0-100 (es: %(sample)s)."
            ) % {'n': len(out_range), 'sample': sample})

        # Check 6: regime company impostato
        if not company.l10n_it_pdcodm_regime:
            issues.append(_(
                "[Critico] L'azienda non ha regime fiscale impostato. "
                "Il controllo C (regime ↔ conto) potrebbe non funzionare."
            ))

        if not issues:
            self.issues = _("Nessuna anomalia rilevata. Il PdC è coerente.")
        else:
            header = _("Validazione su azienda %s: %d anomalie rilevate.\n\n") % (
                company.name, len(issues),
            )
            self.issues = header + '\n\n'.join(issues)
        self.state = 'done'
        return self._reopen_self()

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
