# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SendToSdiWizard(models.TransientModel):
    _name = 'l10n_it_edi.send.to.sdi.wizard'
    _description = 'Invio massivo fatture a SDI'

    move_ids = fields.Many2many('account.move', string='Fatture da inviare')
    count = fields.Integer(compute='_compute_count')
    mode = fields.Char(compute='_compute_mode')

    @api.depends('move_ids')
    def _compute_count(self):
        for wiz in self:
            wiz.count = len(wiz.move_ids)

    @api.depends('move_ids')
    def _compute_mode(self):
        for wiz in self:
            if wiz.move_ids:
                wiz.mode = wiz.move_ids[0].company_id.l10n_it_edi_pec_mode
            else:
                wiz.mode = 'demo'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            moves = self.env['account.move'].browse(active_ids).filtered(
                lambda m: (
                    m.country_code == 'IT'
                    and m.move_type in ('out_invoice', 'out_refund')
                    and m.state == 'posted'
                    and m.l10n_it_edi_pec_state in (False, 'to_send')
                )
            )
            res['move_ids'] = [(6, 0, moves.ids)]
        return res

    def action_send(self):
        """Invia tutte le fatture selezionate a SDI."""
        self.ensure_one()
        if not self.move_ids:
            raise UserError(_("Nessuna fattura da inviare."))

        errors = []
        sent_count = 0
        for move in self.move_ids:
            try:
                mode = move.company_id.l10n_it_edi_pec_mode
                if mode == 'production':
                    move.action_l10n_it_edi_pec_send()
                elif mode == 'demo':
                    move.action_l10n_it_edi_pec_demo()
                elif mode == 'validation':
                    move.action_l10n_it_edi_pec_validate()
                sent_count += 1
            except UserError as e:
                errors.append(f"{move.name}: {e.args[0]}")
            except Exception as e:
                errors.append(f"{move.name}: {str(e)}")

        message = _("Invio massivo completato: %d/%d fatture elaborate.", sent_count, len(self.move_ids))
        if errors:
            message += _("\n\nErrori:\n%s", '\n'.join(errors))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Invio massivo SDI'),
                'message': message,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }


class ResetDemoWizard(models.TransientModel):
    _name = 'l10n_it_edi.reset.demo.wizard'
    _description = 'Gestisci fatture Demo SDI'

    move_ids = fields.Many2many('account.move', string='Fatture demo')
    action_type = fields.Selection(
        selection=[
            ('reset', 'Resetta a "Da inviare" (mantieni fatture)'),
            ('delete', 'Cancella fatture demo (solo bozze)'),
        ],
        string='Azione',
        default='reset',
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            moves = self.env['account.move'].browse(active_ids).filtered(
                lambda m: m.l10n_it_edi_pec_state == 'demo'
            )
            res['move_ids'] = [(6, 0, moves.ids)]
        return res

    def action_confirm(self):
        self.ensure_one()
        if self.action_type == 'reset':
            self.move_ids.action_l10n_it_edi_pec_reset_demo()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Reset Demo'),
                    'message': _("%d fatture resettate a 'Da inviare'.", len(self.move_ids)),
                    'type': 'success',
                },
            }
        elif self.action_type == 'delete':
            count = len(self.move_ids)
            self.move_ids.action_l10n_it_edi_pec_delete_demo()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Cancellazione Demo'),
                    'message': _("%d fatture demo cancellate.", count),
                    'type': 'success',
                },
            }
        return {'type': 'ir.actions.act_window_close'}
