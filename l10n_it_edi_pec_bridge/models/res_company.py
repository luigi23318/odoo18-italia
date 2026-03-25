# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ── Modalità operativa ──────────────────────────────────────────────
    l10n_it_edi_pec_mode = fields.Selection(
        selection=[
            ('demo', 'Demo (simula invio e risposte, nessuna PEC inviata)'),
            ('validation', 'Validazione (genera XML e controlli, senza invio)'),
            ('production', 'Produzione (invio reale a SDI via PEC)'),
        ],
        string='Modalità SDI PEC',
        default='demo',
        required=True,
        help="Demo: simula invio e risposte SDI senza inviare PEC.\n"
             "Validazione: genera e valida XML, scaricabile per verifica su portale AdE.\n"
             "Produzione: invio reale a SDI tramite PEC.",
    )

    # ── Server PEC ──────────────────────────────────────────────────────
    l10n_it_edi_pec_server_out_id = fields.Many2one(
        'ir.mail_server',
        string='Server PEC in uscita (SMTP)',
        help="Server SMTP della casella PEC dedicata alla fatturazione elettronica.\n"
             "Es: smtps://smtp.pec.aruba.it:465",
    )
    l10n_it_edi_pec_server_in_id = fields.Many2one(
        'fetchmail.server',
        string='Server PEC in entrata (IMAP)',
        help="Server IMAP della casella PEC dedicata alla fatturazione elettronica.\n"
             "Es: imaps://imappec.aruba.it:993",
    )
    l10n_it_edi_pec_address = fields.Char(
        string='Indirizzo PEC dedicato SDI',
        help="Es: sdi@tuaazienda.pec.it — Casella PEC dedicata esclusivamente "
             "alla fatturazione elettronica.",
    )
    l10n_it_edi_pec_sdi_address = fields.Char(
        string='Indirizzo PEC SDI',
        default='sdi01@pec.fatturapa.it',
        help="Indirizzo PEC del Sistema di Interscambio. "
             "Non modificare salvo indicazioni diverse dall'AdE.",
    )

    # ── Gestione casella PEC ────────────────────────────────────────────
    l10n_it_edi_pec_cleanup_mode = fields.Selection(
        selection=[
            ('keep', 'Mantieni sul server (marca come letta)'),
            ('delete_now', 'Elimina dal server immediatamente (marca come letta)'),
            ('delete_delay', 'Elimina dal server dopo N giorni (marca come letta)'),
        ],
        string='Gestione email elaborate',
        default='delete_delay',
        help="Cosa fare con le email PEC dopo averle elaborate.\n"
             "In ogni caso le email vengono sempre marcate come lette.",
    )
    l10n_it_edi_pec_cleanup_days = fields.Integer(
        string='Giorni prima dell\'eliminazione',
        default=7,
        help="Numero di giorni dopo i quali le email elaborate vengono "
             "eliminate dal server PEC. Valido solo con modalità 'elimina dopo N giorni'.",
    )
