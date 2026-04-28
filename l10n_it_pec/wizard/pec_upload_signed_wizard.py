# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import base64
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PecUploadSignedWizard(models.TransientModel):
    _name = 'l10n_it_pec.upload.signed.wizard'
    _description = 'Upload XML firmato digitalmente'

    move_id = fields.Many2one('account.move', required=True)
    signed_file = fields.Binary(string="File XML firmato", required=True)
    signed_filename = fields.Char(string="Nome file")

    def action_upload(self):
        """Valida e allega il file firmato alla fattura."""
        self.ensure_one()

        if not self.signed_file:
            raise UserError(_("Selezionare un file."))

        filename = self.signed_filename or ''

        # Validazione filename: solo .xml.p7m (CAdES) o .xml (XAdES)
        if not (filename.lower().endswith('.xml.p7m') or filename.lower().endswith('.xml')):
            raise UserError(_(
                "Formato file non valido. Sono accettati solo:\n"
                "- .xml.p7m (firma CAdES)\n"
                "- .xml (firma XAdES enveloped)"
            ))

        # Validazione contenuto P7M
        file_content = base64.b64decode(self.signed_file)

        if filename.lower().endswith('.xml.p7m'):
            # Verificare header ASN.1/DER: file PKCS#7 iniziano con 0x30 (SEQUENCE tag)
            if len(file_content) < 2 or file_content[0] != 0x30:
                raise UserError(_(
                    "Il file non sembra essere un file .p7m valido. "
                    "Assicurarsi di aver firmato il file con il software di firma digitale."
                ))

        # Validazione corrispondenza filename
        expected_xml_name = self._get_expected_xml_filename()
        if expected_xml_name:
            base_name = filename
            if base_name.lower().endswith('.p7m'):
                base_name = base_name[:-4]  # rimuove .p7m -> resta .xml
            if base_name != expected_xml_name:
                raise UserError(_(
                    "Il nome del file firmato non corrisponde alla fattura.\n"
                    "Atteso: %(expected)s\n"
                    "Ricevuto: %(received)s",
                    expected=expected_xml_name,
                    received=base_name,
                ))

        # Rimuovere eventuale attachment firmato precedente (solo scollega)
        self.move_id.l10n_it_pec_signed_attachment_id = False

        # Rimuovere l'XML generato per il download (non serve più, c'è il .p7m)
        self.move_id.write({
            'l10n_it_pec_xml_attachment_id': False,
            'l10n_it_edi_attachment_file': False,
        })
        self.move_id.invalidate_recordset(
            fnames=['l10n_it_edi_attachment_id', 'l10n_it_edi_attachment_file']
        )

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': self.signed_file,
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'type': 'binary',
        })

        self.move_id.l10n_it_pec_signed_attachment_id = attachment.id

        # Reload per aggiornare la vista allegati
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _get_expected_xml_filename(self):
        """Recupera il filename XML atteso dalla fattura."""
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.move_id.id),
            ('name', '=like', 'IT%.xml'),
        ], limit=1, order='create_date desc')
        return attachment.name if attachment else False
