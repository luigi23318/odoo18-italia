# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_it_edi_pec_mode = fields.Selection(
        related='company_id.l10n_it_edi_pec_mode',
        readonly=False,
    )
    l10n_it_pec_email = fields.Char(
        related='company_id.l10n_it_pec_email',
        readonly=False,
    )
    l10n_it_pec_smtp_server = fields.Char(
        related='company_id.l10n_it_pec_smtp_server',
        readonly=False,
    )
    l10n_it_pec_smtp_port = fields.Integer(
        related='company_id.l10n_it_pec_smtp_port',
        readonly=False,
    )
    l10n_it_pec_smtp_user = fields.Char(
        related='company_id.l10n_it_pec_smtp_user',
        readonly=False,
    )
    l10n_it_pec_smtp_password = fields.Char(
        related='company_id.l10n_it_pec_smtp_password',
        readonly=False,
    )
    l10n_it_pec_smtp_security = fields.Selection(
        related='company_id.l10n_it_pec_smtp_security',
        readonly=False,
    )
    l10n_it_pec_imap_server = fields.Char(
        related='company_id.l10n_it_pec_imap_server',
        readonly=False,
    )
    l10n_it_pec_imap_port = fields.Integer(
        related='company_id.l10n_it_pec_imap_port',
        readonly=False,
    )
    l10n_it_pec_imap_user = fields.Char(
        related='company_id.l10n_it_pec_imap_user',
        readonly=False,
    )
    l10n_it_pec_imap_password = fields.Char(
        related='company_id.l10n_it_pec_imap_password',
        readonly=False,
    )
    l10n_it_pec_sdi_address = fields.Char(
        related='company_id.l10n_it_pec_sdi_address',
        readonly=False,
    )
    l10n_it_pec_sdi_test_address = fields.Char(
        related='company_id.l10n_it_pec_sdi_test_address',
        readonly=False,
    )
