# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import logging

from odoo import _, api, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Mappa per il controllo A (SPEC 6.1): per ogni tipo di documento
# (move_type), elenco degli account_type ammessi sulle righe.
# Riprodotta tale e quale dalla SPEC 6.1.
_CAUSALE_EXPECTED_TYPES = {
    'out_invoice': ['income', 'income_other', 'expense'],
    'out_refund': ['income', 'income_other', 'expense'],
    'in_invoice': [
        'expense', 'expense_direct_cost', 'expense_depreciation',
        'asset_fixed', 'asset_non_current', 'asset_current',
    ],
    'in_refund': [
        'expense', 'expense_direct_cost', 'income', 'income_other',
    ],
}


class AccountMove(models.Model):
    """Estensione di account.move per:
    - Controllo A: coerenza causale ↔ tipo conto al _post (SPEC 6.1).
    - Trigger del lock di immutabilità del PdC alla prima scrittura
      registrata (SPEC 5.4).
    """
    _inherit = 'account.move'

    @api.model_create_multi
    def create(self, vals_list):
        """Override per ricalcolare il lock state quando viene creata
        una nuova scrittura (anche solo bozza).

        Dalla nuova definizione di lock (Sessione 12+), il PdC è
        bloccato se ci sono scritture in stato draft OR posted.
        Quindi una bozza appena creata deve già scattare il lock.

        Skip dell'overhead se nessuna company coinvolta ha il PdC
        OdooManager attivo (caso comune su company non-italiane).
        """
        moves = super().create(vals_list)
        companies_to_recompute = moves.mapped('company_id').filtered(
            lambda c: c.l10n_it_pdcodm_enabled and not c.l10n_it_pdcodm_locked
        )
        if companies_to_recompute:
            companies_to_recompute._recompute_pdcodm_locked()
        return moves

    def _post(self, soft=True):
        """Override per:
        (a) applicare i controlli stringenti italiani prima del post;
        (b) ricalcolare il lock del PdC OdooManager dopo il post.
        """
        # (a) Controllo A: solo per company con PdC OdooManager attivo
        # E strict_mode attivo. Skip se il move è di tipo 'entry' o
        # 'in_receipt'/'out_receipt' (tipologie non coperte dalla SPEC).
        for move in self:
            company = move.company_id
            if not company.l10n_it_pdcodm_enabled:
                continue
            if not company.l10n_it_pdcodm_strict_mode:
                continue
            move._l10n_it_pdcodm_check_causale_coerence()

        result = super()._post(soft=soft)

        # (b) Trigger lock-state recompute dopo _post.
        # Quando una scrittura passa a 'posted', il count di posted
        # cresce → la company può entrare in stato locked.
        companies_to_recompute = self.mapped('company_id').filtered(
            lambda c: c.l10n_it_pdcodm_enabled and not c.l10n_it_pdcodm_locked
        )
        if companies_to_recompute:
            companies_to_recompute._recompute_pdcodm_locked()

        return result

    def button_draft(self):
        """Override per ricalcolare il lock state quando una scrittura
        torna da `posted` a `draft`.

        Senza questo override, il flag `l10n_it_pdcodm_locked` resta
        True anche se l'utente ha riportato a bozza tutte le scritture
        posted — impedendo la disinstallazione del PdC OdooManager.
        """
        result = super().button_draft()
        # Recompute solo per company già lockate che usano il PdC
        # (la transizione locked → unlocked richiede questo trigger)
        companies_to_recompute = self.mapped('company_id').filtered(
            lambda c: c.l10n_it_pdcodm_enabled and c.l10n_it_pdcodm_locked
        )
        if companies_to_recompute:
            companies_to_recompute._recompute_pdcodm_locked()
        return result

    def unlink(self):
        """Override per ricalcolare il lock state quando una scrittura
        viene eliminata. Stesso pattern di `button_draft`.
        """
        # Salvo le company PRIMA di unlink (dopo, self è vuoto)
        companies = self.mapped('company_id').filtered(
            lambda c: c.l10n_it_pdcodm_enabled and c.l10n_it_pdcodm_locked
        )
        result = super().unlink()
        if companies:
            companies._recompute_pdcodm_locked()
        return result

    def _l10n_it_pdcodm_check_causale_coerence(self):
        """Controllo A: coerenza tra `move_type` e `account_type` delle
        righe (SPEC 6.1).

        Esempio: una fattura cliente (`out_invoice`) NON può avere
        righe su un conto patrimoniale di banca o cassa — solo conti
        di ricavo (o eventualmente di costo per rimborsi).
        """
        self.ensure_one()
        if self.move_type not in _CAUSALE_EXPECTED_TYPES:
            return
        expected = _CAUSALE_EXPECTED_TYPES[self.move_type]
        for line in self.invoice_line_ids:
            if not line.account_id:
                continue
            if line.account_id.account_type not in expected:
                raise ValidationError(_(
                    "Incoerenza nella scrittura %(move)s: la riga sul "
                    "conto %(code)s — %(name)s ha tipo \"%(actual)s\" "
                    "che non è compatibile con un documento di tipo "
                    "%(move_type)s.\n\n"
                    "Tipi attesi per questo documento: %(expected)s.\n\n"
                    "Per disabilitare temporaneamente questi controlli, "
                    "togli il flag \"Strict mode\" dalla configurazione "
                    "dell'azienda."
                ) % {
                    'move': self.name or _("(senza numero)"),
                    'code': line.account_id.code,
                    'name': line.account_id.name,
                    'actual': line.account_id.account_type,
                    'move_type': self.move_type,
                    'expected': ', '.join(expected),
                })
