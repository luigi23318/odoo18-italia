from odoo import models
import smtplib
from email.message import EmailMessage

class EdiFormatPec(models.Model):
    _inherit = 'account.edi.format'

    def _send(self, edi_documents):
        if self.code != 'it_edi_pec':
            return super()._send(edi_documents)

        for doc in edi_documents:
            move = doc.move_id
            try:
                xml = self._export_xml(move)
                self._send_via_pec(move, xml)
                doc.write({'state': 'sent', 'error': False})
            except Exception as e:
                doc.write({'state': 'error', 'error': str(e)})

    def _export_xml(self, move):
        sdi_format = self.env.ref('l10n_it_edi.edi_format_it')
        return sdi_format._export_invoice(move)

    def _send_via_pec(self, move, xml_bytes):
        company = move.company_id

        msg = EmailMessage()
        msg['Subject'] = f"Fattura {move.name}"
        msg['From'] = company.pec_email
        msg['To'] = company.sdi_pec_address

        msg.set_content("Invio fattura elettronica via PEC")

        msg.add_attachment(
            xml_bytes,
            maintype='application',
            subtype='xml',
            filename=f"{move.name}.xml"
        )

        with smtplib.SMTP_SSL(company.pec_smtp_server, company.pec_port) as smtp:
            smtp.login(company.pec_username, company.pec_password)
            smtp.send_message(msg)
