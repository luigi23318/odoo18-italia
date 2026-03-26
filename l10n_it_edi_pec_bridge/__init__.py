# Part of Odoo. See LICENSE file for full copyright and licensing details.
from . import models
from . import wizards


def _uninstall_hook(env):
    """Pulizia automatica alla disinstallazione del modulo."""
    import logging
    _logger = logging.getLogger(__name__)
    # Elimina allegati XML demo e validazione
    demo_attachments = env['ir.attachment'].search([
        ('name', 'like', 'DEMO_%'),
        ('res_model', '=', 'account.move'),
    ])
    validation_attachments = env['ir.attachment'].search([
        ('name', 'like', 'VALIDAZIONE_%'),
        ('res_model', '=', 'account.move'),
    ])
    attachments = demo_attachments | validation_attachments
    if attachments:
        count = len(attachments)
        attachments.unlink()
        _logger.info(
            "Disinstallazione l10n_it_edi_pec_bridge: "
            "eliminati %d allegati demo/validazione.", count,
        )
