# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Pattern Passepartout-compatibile (SPEC 14.1): 6 cifre numeriche XYYZZZ.
_CODE_PATTERN = re.compile(r'^\d{6}$')


class PdcodmDuplicateAccountWizard(models.TransientModel):
    """Wizard "Duplica conto" (SPEC 7.4).

    Permette di creare un conto `origin='user'` partendo da un conto
    esistente del PdC OdooManager come template. Il nuovo conto eredita
    tutti i metadati italiani (CEE, deducibilità, regime) e diventa
    modificabile finché non viene usato in una scrittura.
    """
    _name = 'l10n_it_pdcodm.duplicate.account.wizard'
    _description = "Wizard duplicazione conto del PdC OdooManager"

    source_account_id = fields.Many2one(
        'account.account',
        string="Conto modello",
        required=True,
        help="Conto esistente da cui ereditare metadati (CEE, deducibilità, "
             "regime, tipo). Il codice e la descrizione vanno specificati a parte.",
    )
    source_code = fields.Char(
        related='source_account_id.code',
        string="Codice modello",
        readonly=True,
    )
    source_name = fields.Char(
        related='source_account_id.name',
        string="Descrizione modello",
        readonly=True,
    )
    source_account_type = fields.Selection(
        related='source_account_id.account_type',
        string="Tipo conto",
        readonly=True,
    )
    source_cee_code = fields.Char(
        related='source_account_id.l10n_it_pdcodm_cee_code',
        string="CEE",
        readonly=True,
    )
    new_code = fields.Char(
        string="Nuovo codice",
        required=True,
        help="Codice del nuovo conto. Formato: 6 cifre numeriche (XYYZZZ).",
    )
    new_name = fields.Char(
        string="Nuova descrizione",
        required=True,
    )

    @api.constrains('new_code')
    def _check_new_code(self):
        for w in self:
            if not _CODE_PATTERN.match(w.new_code or ''):
                raise ValidationError(_(
                    "Il codice deve essere composto da esattamente 6 cifre "
                    "numeriche (es. 600500). Hai inserito: %r"
                ) % w.new_code)

    def action_create(self):
        """Crea il nuovo conto come copia del template, con
        `origin='user'` e codice/nome forniti dall'utente.
        """
        self.ensure_one()
        if not _CODE_PATTERN.match(self.new_code or ''):
            raise UserError(_(
                "Il codice deve essere composto da 6 cifre numeriche."
            ))
        # Verifica unicità del codice sulla company corrente
        existing = self.env['account.account'].sudo().search([
            ('code', '=', self.new_code),
            ('company_ids', 'in', self.env.company.id),
        ], limit=1)
        if existing:
            raise UserError(_(
                "Il codice %(code)s è già usato dal conto \"%(name)s\" "
                "sull'azienda corrente. Scegli un codice diverso."
            ) % {'code': self.new_code, 'name': existing.name})

        # Duplica con override origin='user'
        new_account = self.source_account_id.copy({
            'code': self.new_code,
            'name': self.new_name,
            'l10n_it_pdcodm_origin': 'user',
        })

        # Apri il form del nuovo conto
        return {
            'type': 'ir.actions.act_window',
            'name': _("Conto creato: %s") % new_account.code,
            'res_model': 'account.account',
            'res_id': new_account.id,
            'view_mode': 'form',
            'target': 'current',
        }
