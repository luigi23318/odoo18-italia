# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ── Modalità di trasmissione SDI ──────────────────────────────────
    l10n_it_edi_pec_mode = fields.Selection(
        selection=[
            ('demo', 'Demo (dry-run, nessun invio)'),
            ('test', 'Test (invio a PEC di test)'),
            ('production', 'Produzione'),
        ],
        string='Modalità PEC SDI',
        default='demo',
        help=(
            "Demo: genera l'XML e simula l'invio senza spedire nulla (dry-run).\n"
            "Test: invia realmente via PEC a un indirizzo di test.\n"
            "Produzione: invia via PEC all'indirizzo SDI ufficiale."
        ),
    )

    # ── Credenziali PEC (SMTP per invio) ──────────────────────────────
    l10n_it_pec_email = fields.Char(
        string='Indirizzo PEC',
        help="Indirizzo PEC mittente registrato presso lo SDI.",
    )
    l10n_it_pec_smtp_server = fields.Char(
        string='Server SMTP PEC',
        help="Es: smtps.pec.aruba.it",
    )
    l10n_it_pec_smtp_port = fields.Integer(
        string='Porta SMTP PEC',
        default=465,
        help="Porta SSL per l'invio PEC (default 465).",
    )
    l10n_it_pec_smtp_user = fields.Char(
        string='Utente SMTP PEC',
    )
    l10n_it_pec_smtp_password = fields.Char(
        string='Password SMTP PEC',
    )
    l10n_it_pec_smtp_security = fields.Selection(
        selection=[
            ('ssl', 'SSL/TLS'),
            ('starttls', 'STARTTLS'),
        ],
        string='Sicurezza SMTP',
        default='ssl',
    )

    # ── Credenziali PEC (IMAP per ricezione notifiche) ────────────────
    l10n_it_pec_imap_server = fields.Char(
        string='Server IMAP PEC',
        help="Es: imaps.pec.aruba.it",
    )
    l10n_it_pec_imap_port = fields.Integer(
        string='Porta IMAP PEC',
        default=993,
    )
    l10n_it_pec_imap_user = fields.Char(
        string='Utente IMAP PEC',
    )
    l10n_it_pec_imap_password = fields.Char(
        string='Password IMAP PEC',
    )

    # ── Indirizzi SDI ─────────────────────────────────────────────────
    l10n_it_pec_sdi_address = fields.Char(
        string='Indirizzo PEC SDI',
        default='sdi01@pec.fatturapa.it',
        help=(
            "Indirizzo PEC dello SDI per l'invio delle fatture.\n"
            "Produzione: sdi01@pec.fatturapa.it\n"
            "L'indirizzo di test va configurato in base "
            "all'accreditamento sul portale FatturePa."
        ),
    )
    l10n_it_pec_sdi_test_address = fields.Char(
        string='Indirizzo PEC SDI (Test)',
        help="Indirizzo PEC per l'ambiente di test SDI, se diverso.",
    )

    # ── Helper: indirizzo destinatario effettivo ──────────────────────
    @api.depends('l10n_it_edi_pec_mode')
    def _get_pec_sdi_destination(self):
        """Restituisce l'indirizzo PEC di destinazione in base alla modalità."""
        self.ensure_one()
        if self.l10n_it_edi_pec_mode == 'test' and self.l10n_it_pec_sdi_test_address:
            return self.l10n_it_pec_sdi_test_address
        return self.l10n_it_pec_sdi_address

    # ── Validazione ───────────────────────────────────────────────────
    def _check_pec_configuration(self):
        """Verifica che la configurazione PEC sia completa per la modalità attiva."""
        self.ensure_one()
        if self.l10n_it_edi_pec_mode in ('test', 'production'):
            missing = []
            if self.l10n_it_edi_pec_mode == 'production':
                if not self.l10n_it_pec_email:
                    missing.append(_("Indirizzo PEC"))
            if not self.l10n_it_pec_smtp_server:
                missing.append(_("Server SMTP PEC"))
            if not self.l10n_it_pec_smtp_user:
                missing.append(_("Utente SMTP PEC"))
            if not self.l10n_it_pec_smtp_password:
                missing.append(_("Password SMTP PEC"))
            if self.l10n_it_edi_pec_mode == 'production':
                if not self.l10n_it_pec_sdi_address:
                    missing.append(_("Indirizzo PEC SDI"))
            if missing:
                raise ValidationError(
                    _("Configurazione PEC incompleta. Campi mancanti:\n%s")
                    % '\n'.join(f"- {m}" for m in missing)
                )

    def action_test_pec_connection(self):
        """Testa la connessione SMTP PEC."""
        self.ensure_one()
        self._check_pec_configuration()

        import smtplib
        try:
            if self.l10n_it_pec_smtp_security == 'ssl':
                server = smtplib.SMTP_SSL(
                    self.l10n_it_pec_smtp_server,
                    self.l10n_it_pec_smtp_port,
                    timeout=10,
                )
            else:
                server = smtplib.SMTP(
                    self.l10n_it_pec_smtp_server,
                    self.l10n_it_pec_smtp_port,
                    timeout=10,
                )
                server.starttls()

            server.login(self.l10n_it_pec_smtp_user, self.l10n_it_pec_smtp_password)
            server.quit()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Connessione PEC riuscita"),
                    'message': _("La connessione SMTP PEC è stata verificata con successo."),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            raise UserError(
                _("Errore connessione SMTP PEC:\n%s") % str(e)
            )

    def action_test_pec_imap_connection(self):
        """Testa la connessione IMAP PEC."""
        self.ensure_one()
        import imaplib
        try:
            if not self.l10n_it_pec_imap_server:
                raise UserError(_("Server IMAP non configurato."))
            imap = imaplib.IMAP4_SSL(
                self.l10n_it_pec_imap_server,
                self.l10n_it_pec_imap_port,
            )
            imap.login(
                self.l10n_it_pec_imap_user or self.l10n_it_pec_smtp_user,
                self.l10n_it_pec_imap_password or self.l10n_it_pec_smtp_password,
            )
            imap.select('INBOX')
            status, messages = imap.search(None, 'ALL')
            count = len(messages[0].split()) if messages[0] else 0
            imap.logout()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Connessione IMAP PEC riuscita"),
                    'message': _("Connesso con successo. Messaggi in inbox: %d") % count,
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            raise UserError(
                _("Errore connessione IMAP PEC:\n%s") % str(e)
            )
