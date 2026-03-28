from odoo import models

class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_edi_formats(self):
        formats = super()._get_edi_formats()
        company = self.company_id

        if company.l10n_it_edi_transmission_mode == 'pec':
            formats = formats.filtered(lambda f: f.code != 'l10n_it_edi')
            pec_format = self.env.ref('odoo_edi_pec.edi_format_it_pec')
            formats |= pec_format

        return formats
