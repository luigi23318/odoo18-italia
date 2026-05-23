# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
from odoo import _, api, models
from odoo.exceptions import ValidationError


class AccountMoveLine(models.Model):
    """Estensione di account.move.line per il controllo C (SPEC 6.2):
    coerenza tra regime fiscale della company e regimi compatibili
    del conto.
    """
    _inherit = 'account.move.line'

    @api.constrains('account_id', 'company_id')
    def _l10n_it_pdcodm_check_regime_compatibility(self):
        """Verifica che il conto usato sia compatibile con il regime
        fiscale della company (SPEC 6.2).

        Saltato se:
        - company non ha PdC OdooManager attivo, o
        - strict_mode è disattivato, o
        - il conto non è origin='standard' (gli external e user non
          hanno regime vincolante), o
        - il campo `l10n_it_pdcodm_regime` del conto è vuoto
          (= universale, compatibile con tutti).
        """
        for line in self:
            company = line.company_id
            if not company.l10n_it_pdcodm_enabled:
                continue
            if not company.l10n_it_pdcodm_strict_mode:
                continue
            account = line.account_id
            if not account or account.l10n_it_pdcodm_origin != 'standard':
                continue
            regimes_raw = account.l10n_it_pdcodm_regime or ''
            regimes = {r.strip() for r in regimes_raw.split(',') if r.strip()}
            if not regimes:
                # Conto universale → ammesso per tutti i regimi
                continue
            if company.l10n_it_pdcodm_regime in regimes:
                continue
            # Conto non compatibile: produci messaggio specifico se è
            # un conto storico e l'azienda non lo include.
            if 'storico' in regimes and not company.l10n_it_pdcodm_include_storico:
                raise ValidationError(_(
                    "Il conto %(code)s — %(name)s è riservato al regime "
                    "'storico' (ammortamento anticipato, obsoleto dal 2008).\n\n"
                    "Per usarlo, attiva il flag \"Includi conti storici\" "
                    "nella configurazione dell'azienda."
                ) % {
                    'code': account.code,
                    'name': account.name,
                })
            raise ValidationError(_(
                "Il conto %(code)s — %(name)s è riservato ai regimi "
                "%(regimes)s, ma l'azienda %(company)s è configurata per "
                "il regime '%(company_regime)s'.\n\n"
                "Per disabilitare temporaneamente questi controlli, togli "
                "il flag \"Strict mode\" dalla configurazione dell'azienda."
            ) % {
                'code': account.code,
                'name': account.name,
                'regimes': ', '.join(sorted(regimes)),
                'company': company.name,
                'company_regime': company.l10n_it_pdcodm_regime or '?',
            })
