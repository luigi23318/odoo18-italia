# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class AccountMoveSend(models.TransientModel):
    _inherit = 'account.move.send'

    l10n_it_pec_send = fields.Boolean(
        string='Invia via PEC allo SDI',
        compute='_compute_l10n_it_pec_send',
        store=True,
        readonly=False,
    )

    l10n_it_pec_mode_display = fields.Char(
        string='Modalità PEC',
        compute='_compute_l10n_it_pec_mode_display',
    )

    @api.depends('move_ids')
    def _compute_l10n_it_pec_send(self):
        for wizard in self:
            moves = wizard.move_ids
            if moves:
                company = moves[0].company_id
                wizard.l10n_it_pec_send = company.l10n_it_edi_pec_mode in (
                    'demo', 'test', 'production'
                )
            else:
                wizard.l10n_it_pec_send = False

    @api.depends('move_ids')
    def _compute_l10n_it_pec_mode_display(self):
        mode_labels = {
            'disabled': _('Disabilitato'),
            'demo': _('Demo (dry-run)'),
            'test': _('Test'),
            'production': _('Produzione'),
        }
        for wizard in self:
            moves = wizard.move_ids
            if moves:
                mode = moves[0].company_id.l10n_it_edi_pec_mode
                wizard.l10n_it_pec_mode_display = mode_labels.get(mode, '')
            else:
                wizard.l10n_it_pec_mode_display = ''

    def _call_web_service_before_invoice_pdf_render(self, invoices_data):
        """
        Override CHIAVE per l'integrazione nel wizard "Invia e Stampa".

        In Odoo 18, questo metodo viene chiamato dal wizard account.move.send
        PRIMA di generare il PDF. È qui che i moduli EDI (come l10n_it_edi,
        l10n_ro_edi, l10n_my_edi) agganciano l'invio al web service.

        Se PEC è attivo e l'utente ha selezionato l'invio PEC nel wizard,
        intercettiamo qui e usiamo il trasporto PEC.
        """
        # Se PEC non è selezionato, lascia fare al flusso standard
        if not self.l10n_it_pec_send:
            return super()._call_web_service_before_invoice_pdf_render(invoices_data)

        # Filtra le fatture italiane che devono andare via PEC
        pec_invoice_ids = set()
        for move, invoice_data in invoices_data.items():
            if (
                move._l10n_it_edi_pec_is_active()
                and move.move_type in ('out_invoice', 'out_refund')
                and move.state == 'posted'
            ):
                pec_invoice_ids.add(move.id)

        # Le fatture PEC le gestiamo noi
        if pec_invoice_ids:
            pec_moves = self.env['account.move'].browse(list(pec_invoice_ids))
            for move in pec_moves:
                try:
                    move._l10n_it_pec_send_to_sdi()
                except Exception as e:
                    _logger.exception(
                        "Errore PEC nel wizard per fattura %s", move.name
                    )
                    move.l10n_it_pec_last_error = str(e)
                    move.message_post(
                        body=_("❌ Errore invio PEC dal wizard: %s") % str(e),
                        message_type='notification',
                        subtype_xmlid='mail.mt_note',
                    )

        # Le fatture NON-PEC vanno al flusso standard
        remaining_data = {
            move: data for move, data in invoices_data.items()
            if move.id not in pec_invoice_ids
        }
        if remaining_data:
            super()._call_web_service_before_invoice_pdf_render(remaining_data)

    @api.model
    def _get_wizard_vals_restrict_to(self, move):
        """
        Aggiunge il campo PEC al wizard se disponibile.
        """
        vals = super()._get_wizard_vals_restrict_to(move)
        if move.company_id.l10n_it_edi_pec_mode != 'disabled':
            vals['l10n_it_pec_send'] = True
        return vals
