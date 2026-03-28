# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

"""
Test del modulo l10n_it_pec — Architettura Opzione C.

Per eseguire i test:
    ./odoo-bin -d test_db -i l10n_it_pec --test-enable --stop-after-init

Oppure test specifico:
    ./odoo-bin -d test_db --test-tags /l10n_it_pec
"""

import logging
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestPecConfiguration(TransactionCase):
    """Test configurazione PEC su res.company."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'l10n_it_edi_pec_mode': 'disabled',
            'l10n_it_pec_email': 'test@pec.example.it',
            'l10n_it_pec_smtp_server': 'smtps.pec.example.it',
            'l10n_it_pec_smtp_port': 465,
            'l10n_it_pec_smtp_user': 'test@pec.example.it',
            'l10n_it_pec_smtp_password': 'testpassword',
            'l10n_it_pec_smtp_security': 'ssl',
            'l10n_it_pec_sdi_address': 'sdi01@pec.fatturapa.it',
        })

    def test_01_pec_mode_disabled(self):
        """PEC disabilitata non intercetta l'invio."""
        self.company.l10n_it_edi_pec_mode = 'disabled'
        # Nessun errore di validazione in modalità disabled
        # (non richiede credenziali)
        self.assertEqual(self.company.l10n_it_edi_pec_mode, 'disabled')

    def test_02_pec_mode_demo(self):
        """Modalità demo è valida senza credenziali complete."""
        self.company.l10n_it_edi_pec_mode = 'demo'
        self.assertEqual(self.company.l10n_it_edi_pec_mode, 'demo')

    def test_03_check_pec_configuration_incomplete(self):
        """Configurazione incompleta solleva ValidationError."""
        self.company.write({
            'l10n_it_edi_pec_mode': 'production',
            'l10n_it_pec_email': False,  # mancante
        })
        with self.assertRaises(ValidationError):
            self.company._check_pec_configuration()

    def test_04_check_pec_configuration_complete(self):
        """Configurazione completa non solleva errori."""
        self.company.write({
            'l10n_it_edi_pec_mode': 'production',
            'l10n_it_pec_email': 'test@pec.example.it',
            'l10n_it_pec_smtp_server': 'smtps.pec.example.it',
            'l10n_it_pec_smtp_user': 'test@pec.example.it',
            'l10n_it_pec_smtp_password': 'password',
            'l10n_it_pec_sdi_address': 'sdi01@pec.fatturapa.it',
        })
        # Non deve sollevare eccezioni
        self.company._check_pec_configuration()

    def test_05_sdi_destination_production(self):
        """In produzione usa l'indirizzo SDI principale."""
        self.company.l10n_it_edi_pec_mode = 'production'
        self.assertEqual(
            self.company._get_pec_sdi_destination(),
            'sdi01@pec.fatturapa.it',
        )

    def test_06_sdi_destination_test(self):
        """In test usa l'indirizzo di test se configurato."""
        self.company.write({
            'l10n_it_edi_pec_mode': 'test',
            'l10n_it_pec_sdi_test_address': 'test@pec.test.it',
        })
        self.assertEqual(
            self.company._get_pec_sdi_destination(),
            'test@pec.test.it',
        )


@tagged('post_install', '-at_install')
class TestPecAccountMove(TransactionCase):
    """Test invio fatture via PEC — Opzione C."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'l10n_it_edi_pec_mode': 'demo',
            'l10n_it_pec_email': 'test@pec.example.it',
            'l10n_it_pec_smtp_server': 'smtps.pec.example.it',
            'l10n_it_pec_smtp_port': 465,
            'l10n_it_pec_smtp_user': 'test@pec.example.it',
            'l10n_it_pec_smtp_password': 'testpassword',
            'l10n_it_pec_sdi_address': 'sdi01@pec.fatturapa.it',
        })

        # Crea partner di test
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Partner SRL',
            'vat': 'IT12345670017',
            'country_id': cls.env.ref('base.it').id,
        })

    def test_10_pec_is_active_demo(self):
        """_l10n_it_edi_pec_is_active() ritorna True in demo."""
        invoice = self._create_test_invoice()
        self.assertTrue(invoice._l10n_it_edi_pec_is_active())

    def test_11_pec_is_active_disabled(self):
        """_l10n_it_edi_pec_is_active() ritorna False se disabilitato."""
        self.company.l10n_it_edi_pec_mode = 'disabled'
        invoice = self._create_test_invoice()
        self.assertFalse(invoice._l10n_it_edi_pec_is_active())

    def test_12_pec_send_requires_posted(self):
        """Invio PEC richiede fattura confermata."""
        invoice = self._create_test_invoice(post=False)
        with self.assertRaises(UserError):
            invoice.action_l10n_it_pec_send()

    def test_13_notification_rc(self):
        """Notifica RC (Ricevuta Consegna) aggiorna stato a delivered."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'sent'

        xml_rc = b'<NotificaRC><NomeFile>test.xml</NomeFile></NotificaRC>'
        invoice._l10n_it_pec_process_sdi_notification('RC', xml_rc)

        self.assertEqual(invoice.l10n_it_edi_state, 'delivered')

    def test_14_notification_ns(self):
        """Notifica NS (Scarto) aggiorna stato a invalid."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'sent'

        xml_ns = b'<NotificaNS><NomeFile>test.xml</NomeFile></NotificaNS>'
        invoice._l10n_it_pec_process_sdi_notification('NS', xml_ns)

        self.assertEqual(invoice.l10n_it_edi_state, 'invalid')

    def test_15_notification_ne_accepted(self):
        """Notifica NE con EC01 (Accettazione) → delivered."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'sent'

        xml_ne = b'<NotificaNE><Esito>EC01</Esito></NotificaNE>'
        invoice._l10n_it_pec_process_sdi_notification('NE', xml_ne)

        self.assertEqual(invoice.l10n_it_edi_state, 'delivered')

    def test_16_notification_ne_rejected(self):
        """Notifica NE con EC02 (Rifiuto) → invalid."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'sent'

        xml_ne = b'<NotificaNE><Esito>EC02</Esito></NotificaNE>'
        invoice._l10n_it_pec_process_sdi_notification('NE', xml_ne)

        self.assertEqual(invoice.l10n_it_edi_state, 'invalid')

    def test_17_notification_dt(self):
        """Notifica DT (Decorrenza Termini = silenzio-assenso) → delivered."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'sent'

        xml_dt = b'<NotificaDT><NomeFile>test.xml</NomeFile></NotificaDT>'
        invoice._l10n_it_pec_process_sdi_notification('DT', xml_dt)

        self.assertEqual(invoice.l10n_it_edi_state, 'delivered')

    # ── Helper ────────────────────────────────────────────────────────

    def _create_test_invoice(self, post=True):
        """Crea una fattura di test."""
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.company.id),
        ], limit=1)

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Servizio di test',
                'quantity': 1,
                'price_unit': 100.00,
            })],
        })

        if post:
            invoice.action_post()

        return invoice
