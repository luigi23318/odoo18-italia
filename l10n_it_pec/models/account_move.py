from odoo import models, fields
import smtplib
from email.message import EmailMessage

class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_it_edi_pec_state = fields.Selection([
        ('draft','Da inviare'),
        ('sent','Inviata'),
        ('error','Errore')
    ], default='draft')

    def _post(self, soft=True):
        res = super()._post(soft)

        for move in self:
            if move.move_type != 'out_invoice':
                continue

            if move.company_id.l10n_it_edi_transmission_mode != 'pec':
                continue

            try:
                move._send_invoice_via_pec()
                move.l10n_it_edi_pec_state = 'sent'
            except Exception as e:
                move.l10n_it_edi_pec_state = 'error'
                move.message_post(body=f"Errore invio PEC: {str(e)}")

        return res

    def _generate_fatturapa_xml(self):
        self.ensure_one()
        sdi_format = self.env.ref('l10n_it_edi.edi_format_it')
        xml, _ = sdi_format._export_invoice(self)
        return xml

    def _send_invoice_via_pec(self):
        self.ensure_one()
        company = self.company_id

        xml = self._generate_fatturapa_xml()

        msg = EmailMessage()
        msg['Subject'] = f"Fattura {self.name}"
        msg['From'] = company.pec_email
        msg['To'] = company.sdi_pec_address

        msg.set_content("Invio fattura elettronica via PEC")

        msg.add_attachment(
            xml,
            maintype='application',
            subtype='xml',
            filename=f"{self.name}.xml"
        )

        with smtplib.SMTP_SSL(company.pec_smtp_server, company.pec_port) as smtp:
            smtp.login(company.pec_username, company.pec_password)
            smtp.send_message(msg)

        self.message_post(body="Fattura inviata via PEC")
