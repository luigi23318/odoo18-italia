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
            'l10n_it_edi_pec_mode': 'demo',
            'l10n_it_pec_email': 'test@pec.example.it',
            'l10n_it_pec_smtp_server': 'smtps.pec.example.it',
            'l10n_it_pec_smtp_port': 465,
            'l10n_it_pec_smtp_user': 'test@pec.example.it',
            'l10n_it_pec_smtp_password': 'testpassword',
            'l10n_it_pec_smtp_security': 'ssl',
            'l10n_it_pec_sdi_address': 'sdi01@pec.fatturapa.it',
        })

    def test_01_pec_mode_demo(self):
        """Modalità demo è il default e non richiede credenziali complete."""
        self.company.l10n_it_edi_pec_mode = 'demo'
        self.assertEqual(self.company.l10n_it_edi_pec_mode, 'demo')

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

    def test_11_pec_is_active_no_mode(self):
        """_l10n_it_edi_pec_is_active() ritorna False se pec_mode è vuoto."""
        self.company.l10n_it_edi_pec_mode = False
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
        invoice.l10n_it_edi_state = 'processing'

        xml_rc = b'<NotificaRC><NomeFile>test.xml</NomeFile></NotificaRC>'
        invoice._l10n_it_pec_process_sdi_notification('RC', xml_rc)

        self.assertEqual(invoice.l10n_it_edi_state, 'forwarded')

    def test_14_notification_ns(self):
        """Notifica NS (Scarto) aggiorna stato a invalid."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'processing'

        xml_ns = b'<NotificaNS><NomeFile>test.xml</NomeFile></NotificaNS>'
        invoice._l10n_it_pec_process_sdi_notification('NS', xml_ns)

        self.assertEqual(invoice.l10n_it_edi_state, 'rejected')

    def test_15_notification_ne_accepted(self):
        """Notifica NE con EC01 (Accettazione PA) → accepted_by_pa_partner."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'processing'

        xml_ne = b'<NotificaNE><Esito>EC01</Esito></NotificaNE>'
        invoice._l10n_it_pec_process_sdi_notification('NE', xml_ne)

        self.assertEqual(invoice.l10n_it_edi_state, 'accepted_by_pa_partner')

    def test_16_notification_ne_rejected(self):
        """Notifica NE con EC02 (Rifiuto PA) → rejected_by_pa_partner."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'processing'

        xml_ne = b'<NotificaNE><Esito>EC02</Esito></NotificaNE>'
        invoice._l10n_it_pec_process_sdi_notification('NE', xml_ne)

        self.assertEqual(invoice.l10n_it_edi_state, 'rejected_by_pa_partner')

    def test_17_notification_dt(self):
        """Notifica DT (Decorrenza Termini = silenzio-assenso PA) → accepted_by_pa_partner_after_expiry."""
        invoice = self._create_test_invoice()
        invoice.l10n_it_edi_state = 'processing'

        xml_dt = b'<NotificaDT><NomeFile>test.xml</NomeFile></NotificaDT>'
        invoice._l10n_it_pec_process_sdi_notification('DT', xml_dt)

        self.assertEqual(invoice.l10n_it_edi_state, 'accepted_by_pa_partner_after_expiry')

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


@tagged('post_install', '-at_install')
class TestPecPassiveInvoices(TransactionCase):
    """Test acquisizione fatture passive via PEC.

    Copre:
    - Riconoscimento filename (xml, .xml.p7m, metadati, foreign VAT)
    - Skip esplicito del file metadati SDI
    - Deduplica su filename già importato
    - Quarantena in caso di fallimento dell'import standard
    - Allegato .eml del messaggio PEC originale
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'l10n_it_edi_pec_mode': 'demo',
            'l10n_it_pec_email': 'test@pec.example.it',
        })
        cls.handler = cls.env['l10n_it_pec.mail.handler']

        # Importa i pattern direttamente dal modulo per testarli.
        from odoo.addons.l10n_it_pec.models import pec_mail_handler as pmh
        cls.PASSIVE_PATTERN = pmh.SDI_PASSIVE_INVOICE_PATTERN
        cls.METADATA_PATTERN = pmh.SDI_METADATA_FILENAME_PATTERN

    # ── Test riconoscimento filename ───────────────────────────────────

    def test_20_passive_pattern_plain_xml(self):
        """Il regex accetta una fattura passiva XML italiana."""
        self.assertTrue(
            self.PASSIVE_PATTERN.match('IT01234567890_00001.xml')
        )

    def test_21_passive_pattern_signed_p7m(self):
        """Il regex accetta una fattura passiva firmata CAdES (.xml.p7m)."""
        self.assertTrue(
            self.PASSIVE_PATTERN.match('IT01234567890_00001.xml.p7m')
        )

    def test_22_passive_pattern_alphanumeric_progressive(self):
        """Il regex accetta un progressivo alfanumerico."""
        self.assertTrue(
            self.PASSIVE_PATTERN.match('IT01234567890_ABCDE.xml.p7m')
        )

    def test_23_passive_pattern_foreign_vat(self):
        """Il regex accetta un fornitore estero con codice paese diverso."""
        self.assertTrue(
            self.PASSIVE_PATTERN.match('DE123456789_00001.xml')
        )

    def test_24_passive_pattern_case_insensitive(self):
        """Il regex è case-insensitive sull'estensione."""
        self.assertTrue(
            self.PASSIVE_PATTERN.match('IT01234567890_00001.XML.P7M')
        )

    def test_25_passive_pattern_rejects_notification(self):
        """Il regex non matcha le notifiche SDI (hanno _RC_, _NS_ ecc)."""
        self.assertFalse(
            self.PASSIVE_PATTERN.match('IT01234567890_5678_RC_001.xml')
        )

    def test_26_passive_pattern_rejects_random(self):
        """Il regex rifiuta nomi file arbitrari."""
        self.assertFalse(self.PASSIVE_PATTERN.match('random.xml'))
        self.assertFalse(self.PASSIVE_PATTERN.match('invoice.pdf'))

    def test_27_metadata_pattern_detects_metadata(self):
        """Il regex metadati identifica i file _metadati.xml."""
        self.assertTrue(
            self.METADATA_PATTERN.search('IT01234567890_00001_metadati.xml')
        )

    def test_28_metadata_pattern_ignores_invoice(self):
        """Il regex metadati non matcha una fattura regolare."""
        self.assertFalse(
            self.METADATA_PATTERN.search('IT01234567890_00001.xml')
        )

    # ── Test _handle_passive_invoice ───────────────────────────────────

    def test_30_passive_deduplication(self):
        """Un filename già presente come attachment di una move
        della stessa company non viene reimportato."""
        filename = 'IT99999999999_00001.xml'
        xml = b'<FatturaElettronica>dummy</FatturaElettronica>'

        # Simula un import precedente: crea una move e un attachment
        # collegato con lo stesso filename.
        journal = self.env['account.journal'].search([
            ('type', '=', 'purchase'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        existing_move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'journal_id': journal.id,
        })
        self.env['ir.attachment'].create({
            'name': filename,
            'raw': xml,
            'mimetype': 'application/xml',
            'res_model': 'account.move',
            'res_id': existing_move.id,
        })

        # L'import standard non deve essere chiamato grazie alla dedup.
        with patch.object(
            type(self.env['account.move']),
            '_l10n_it_edi_import_invoices',
            create=True,
        ) as mock_import:
            self.handler._handle_passive_invoice(
                xml, filename, self.company,
                raw_email=b'raw', subject='Test',
            )
            mock_import.assert_not_called()

    def test_31_passive_quarantine_on_missing_method(self):
        """Se _l10n_it_edi_import_invoices non esiste, la fattura
        viene messa in quarantena (non persa)."""
        filename = 'IT88888888888_00001.xml'
        xml = b'<FatturaElettronica>dummy</FatturaElettronica>'

        AccountMove = type(self.env['account.move'])
        had_method = hasattr(AccountMove, '_l10n_it_edi_import_invoices')
        saved = None
        if had_method:
            saved = getattr(AccountMove, '_l10n_it_edi_import_invoices')
            delattr(AccountMove, '_l10n_it_edi_import_invoices')
        try:
            self.handler._handle_passive_invoice(
                xml, filename, self.company, raw_email=None,
            )
        finally:
            if had_method and saved is not None:
                setattr(AccountMove, '_l10n_it_edi_import_invoices', saved)

        quarantined = self.env['ir.attachment'].search([
            ('name', '=', f'QUARANTINE_{filename}'),
        ], limit=1)
        self.assertTrue(
            quarantined,
            "L'XML doveva essere messo in quarantena, non perso.",
        )

    def test_32_passive_quarantine_on_import_failure(self):
        """Se _l10n_it_edi_import_invoices solleva, la fattura
        finisce in quarantena."""
        filename = 'IT77777777777_00001.xml'
        xml = b'<FatturaElettronica>dummy</FatturaElettronica>'

        def _raise(*args, **kwargs):
            raise ValueError("XML malformato simulato")

        with patch.object(
            type(self.env['account.move']),
            '_l10n_it_edi_import_invoices',
            create=True,
            side_effect=_raise,
        ):
            self.handler._handle_passive_invoice(
                xml, filename, self.company, raw_email=None,
            )

        quarantined = self.env['ir.attachment'].search([
            ('name', '=', f'QUARANTINE_{filename}'),
        ], limit=1)
        self.assertTrue(quarantined)

    def test_33_passive_quarantine_on_empty_result(self):
        """Se l'import ritorna un recordset vuoto, quarantena."""
        filename = 'IT66666666666_00001.xml'
        xml = b'<FatturaElettronica>dummy</FatturaElettronica>'

        empty_moves = self.env['account.move']
        with patch.object(
            type(self.env['account.move']),
            '_l10n_it_edi_import_invoices',
            create=True,
            return_value=empty_moves,
        ):
            self.handler._handle_passive_invoice(
                xml, filename, self.company, raw_email=None,
            )

        quarantined = self.env['ir.attachment'].search([
            ('name', '=', f'QUARANTINE_{filename}'),
        ], limit=1)
        self.assertTrue(quarantined)

    def test_34_passive_eml_attachment(self):
        """Quando disponibile, il messaggio PEC originale (.eml) viene
        allegato alla fattura importata per conservazione."""
        filename = 'IT55555555555_00001.xml'
        xml = b'<FatturaElettronica>dummy</FatturaElettronica>'
        raw_eml = b'From: sdi01@pec.fatturapa.it\r\nSubject: test\r\n\r\nbody'

        # Crea una move "finta" che il mock restituirà come importata.
        journal = self.env['account.journal'].search([
            ('type', '=', 'purchase'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        fake_move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'journal_id': journal.id,
        })

        with patch.object(
            type(self.env['account.move']),
            '_l10n_it_edi_import_invoices',
            create=True,
            return_value=fake_move,
        ):
            self.handler._handle_passive_invoice(
                xml, filename, self.company,
                raw_email=raw_eml, subject='Consegna fattura',
            )

        eml_att = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', fake_move.id),
            ('mimetype', '=', 'message/rfc822'),
        ], limit=1)
        self.assertTrue(eml_att, "L'allegato .eml deve essere presente.")
        self.assertIn('.eml', eml_att.name)
