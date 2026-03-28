from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_it_edi_transmission_mode = fields.Selection([
        ('sdi', 'SDI'),
        ('pec', 'PEC')
    ], default='sdi')

    pec_email = fields.Char()
    pec_username = fields.Char()
    pec_password = fields.Char()
    pec_smtp_server = fields.Char()
    pec_port = fields.Integer(default=465)
    sdi_pec_address = fields.Char(default='sdi01@pec.fatturapa.it')
