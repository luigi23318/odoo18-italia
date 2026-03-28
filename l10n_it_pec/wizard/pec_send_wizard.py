# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PecSendWizard(models.TransientModel):
    _name = 'l10n_it_pec.send.wizard'
    _description = 'Invio fatture via PEC allo SDI'

    move_ids = fields.Many2many(
        'account.move',
        string='Fatture da inviare',
    )
    pec_mode = fields.Selection(
        related='company_id.l10n_it_edi_pec_mode',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
    )
    count_total = fields.Integer(
        string='Fatture selezionate',
        compute='_compute_counts',
    )
    count_sendable = fields.Integer(
        string='Fatture inviabili',
        compute='_compute_counts',
    )
    count_already_sent = fields.Integer(
        string='Già inviate',
        compute='_compute_counts',
    )

    @api.depends('move_ids')
    def _compute_counts(self):
        for wiz in self:
            wiz.count_total = len(wiz.move_ids)
            sendable = wiz.move_ids.filtered(
                lambda m: (
                    m.state == 'posted'
                    and m.move_type in ('out_invoice', 'out_refund')
                    and m.l10n_it_edi_state != 'forwarded'
                )
            )
            wiz.count_sendable = len(sendable)
            wiz.count_already_sent = len(
                wiz.move_ids.filtered(lambda m: m.l10n_it_edi_state == 'forwarded')
            )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            moves = self.env['account.move'].browse(active_ids).filtered(
                lambda m: m.state == 'posted'
                and m.move_type in ('out_invoice', 'out_refund')
            )
            res['move_ids'] = [(6, 0, moves.ids)]
        return res

    def action_send_via_pec(self):
        """Invia le fatture selezionate via PEC."""
        self.ensure_one()

        if self.pec_mode == 'disabled':
            raise UserError(
                _("La modalità PEC è disabilitata. "
                  "Attivare in Impostazioni → Contabilità → PEC SDI.")
            )

        sendable = self.move_ids.filtered(
            lambda m: (
                m.state == 'posted'
                and m.move_type in ('out_invoice', 'out_refund')
                and m.l10n_it_edi_state not in ('forwarded',)
            )
        )

        if not sendable:
            raise UserError(_("Nessuna fattura da inviare."))

        errors = []
        success_count = 0

        for move in sendable:
            try:
                move._l10n_it_pec_send_to_sdi()
                success_count += 1
            except Exception as e:
                errors.append(f"{move.name}: {str(e)}")
                _logger.exception(
                    "Errore invio PEC fattura %s", move.name
                )

        # Messaggio riepilogativo
        message_parts = []
        if success_count:
            message_parts.append(
                _("%d fattura/e inviate con successo via PEC.") % success_count
            )
        if errors:
            message_parts.append(
                _("Errori (%d):\n%s") % (len(errors), '\n'.join(errors))
            )

        msg_type = 'success' if not errors else ('warning' if success_count else 'danger')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Invio PEC completato"),
                'message': '\n'.join(message_parts),
                'type': msg_type,
                'sticky': bool(errors),
            },
        }

    def action_preview_xml(self):
        """Genera XML di anteprima per tutte le fatture selezionate."""
        self.ensure_one()

        sendable = self.move_ids.filtered(
            lambda m: m.state == 'posted'
            and m.move_type in ('out_invoice', 'out_refund')
        )

        if not sendable:
            raise UserError(_("Nessuna fattura confermata selezionata."))

        for move in sendable:
            move.action_l10n_it_pec_preview_xml()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("XML Generati"),
                'message': _("Generati %d file XML (vedi allegati nelle fatture).") % len(sendable),
                'type': 'success',
                'sticky': False,
            },
        }
