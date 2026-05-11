# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import _, api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    def _get_invoice_extra_attachments(self, invoice):
        """Override: se la fattura ha un file .p7m firmato, sostituisce l'XML
        standard con il firmato negli allegati del wizard "Stampa e invia".

        Razionale:
        - Il .p7m contiene al suo interno l'XML originale + firma CAdES.
        - È il documento "ufficiale" trasmesso allo SDI.
        - Per il destinatario è più informativo (può verificare la firma).
        - Comportamento uniforme: PDF + (.p7m se firmato | .xml se non firmato).
        """
        result = super()._get_invoice_extra_attachments(invoice)
        if invoice.l10n_it_pec_signed_attachment_id:
            # Rimuovi l'XML standard (se presente) e sostituiscilo con il .p7m
            if invoice.l10n_it_edi_attachment_id:
                result = result - invoice.l10n_it_edi_attachment_id
            result = result + invoice.l10n_it_pec_signed_attachment_id
        return result

    def _get_alerts(self, moves, moves_data):
        alerts = super()._get_alerts(moves, moves_data)

        # Alert: fatture PA che richiedono firma digitale
        pa_moves_needing_signature = moves.filtered(
            lambda m: (
                'it_edi_send' in moves_data[m].get('extra_edis', {})
                and m._l10n_it_pec_is_pa_invoice()
                and not m.l10n_it_pec_signed_attachment_id
                and m.company_id.l10n_it_edi_pec_mode
            )
        )
        if pa_moves_needing_signature:
            alerts['l10n_it_pec_pa_signature_required'] = {
                'message': _(
                    "Le seguenti fatture sono destinate alla PA e richiedono "
                    "la firma digitale (CAdES .p7m o XAdES .xml) prima dell'invio: %s",
                    ', '.join(pa_moves_needing_signature.mapped('name')),
                ),
                'level': 'warning',
            }

        # Alert: configurazione PEC incompleta
        pec_moves = moves.filtered(
            lambda m: (
                'it_edi_send' in moves_data[m].get('extra_edis', {})
                and m.company_id.l10n_it_edi_pec_mode in ('test', 'production')
            )
        )
        if pec_moves:
            company = pec_moves[0].company_id
            if not company.l10n_it_pec_smtp_server or not company.l10n_it_pec_smtp_user:
                alerts['l10n_it_pec_config_incomplete'] = {
                    'message': _(
                        "Configurazione PEC SMTP incompleta. "
                        "Verificare in Impostazioni → Contabilità → PEC SDI."
                    ),
                    'level': 'danger',
                }

        return alerts
