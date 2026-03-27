# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountMoveSend(models.TransientModel):
    _inherit = 'account.move.send'

    def _get_default_l10n_it_edi_enable(self):
        """Disabilita il checkbox 'Invia all'Agenzia delle Entrate' nel dialogo
        Send & Print quando il modulo PEC bridge è installato.
        L'invio va fatto tramite i pulsanti PEC bridge, non tramite il proxy Odoo SA."""
        return False

    @api.model
    def _get_l10n_it_edi_enable_default(self):
        """Override alternativo per disabilitare l'invio via proxy Odoo."""
        return False

    def _get_wizard_values(self):
        """Override per rimuovere/disabilitare l'opzione di invio all'AdE."""
        values = super()._get_wizard_values()
        # Rimuovi il checkbox EDI italiano se presente
        if 'l10n_it_edi' in values:
            values['l10n_it_edi'] = False
        return values

    @api.model
    def _get_edi_extra_info(self, move):
        """Override per nascondere il checkbox EDI italiano dal dialogo."""
        result = super()._get_edi_extra_info(move)
        if isinstance(result, dict):
            # Rimuovi o disabilita l'opzione italiana
            for key in list(result.keys()):
                if 'l10n_it' in key or 'it_edi' in key:
                    result.pop(key, None)
        return result

    def _get_default_extra_edis(self):
        """Override per non selezionare l'EDI italiano come default."""
        result = super()._get_default_extra_edis()
        if isinstance(result, (list, set)):
            result = [r for r in result if 'l10n_it' not in str(r) and 'it_edi' not in str(r)]
        return result

    @api.depends('move_ids')
    def _compute_l10n_it_edi_enable(self):
        """Forza il checkbox a False."""
        for wizard in self:
            if hasattr(wizard, 'l10n_it_edi_enable'):
                wizard.l10n_it_edi_enable = False

    @api.depends('move_ids')
    def _compute_extra_edis(self):
        """Override per rimuovere l'EDI italiano dalle opzioni extra."""
        super()._compute_extra_edis()
        for wizard in self:
            if hasattr(wizard, 'extra_edis'):
                current = wizard.extra_edis
                if isinstance(current, str) and 'l10n_it' in current:
                    # Rimuovi la voce italiana
                    import json
                    try:
                        edis = json.loads(current)
                        if isinstance(edis, dict):
                            for key in list(edis.keys()):
                                if 'l10n_it' in key or 'it_edi' in key:
                                    edis[key]['checked'] = False
                            wizard.extra_edis = json.dumps(edis)
                    except (json.JSONDecodeError, TypeError):
                        pass
