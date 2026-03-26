# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SdiPecTransaction(models.Model):
    _name = 'sdi.pec.transaction'
    _description = 'Transazione SDI via PEC'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # ── Riferimenti ─────────────────────────────────────────────────────
    move_id = fields.Many2one(
        'account.move',
        string='Fattura',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Azienda',
        related='move_id.company_id',
        store=True,
    )

    # ── Tipo e direzione ────────────────────────────────────────────────
    direction = fields.Selection(
        selection=[
            ('out', 'In uscita (fattura attiva)'),
            ('in', 'In entrata (fattura passiva)'),
        ],
        string='Direzione',
        required=True,
    )
    transaction_type = fields.Selection(
        selection=[
            ('send', 'Invio fattura'),
            ('ricevuta_consegna', 'Ricevuta di consegna (RC)'),
            ('notifica_scarto', 'Notifica di scarto (NS)'),
            ('notifica_mancata_consegna', 'Mancata consegna (MC)'),
            ('notifica_esito', 'Notifica esito committente (NE)'),
            ('notifica_decorrenza', 'Decorrenza termini (DT)'),
            ('attestazione_trasmissione', 'Attestazione trasmissione (AT)'),
            ('receive_invoice', 'Ricezione fattura passiva'),
            ('receive_creditnote', 'Ricezione nota di credito passiva'),
            ('demo_simulation', 'Simulazione demo'),
        ],
        string='Tipo transazione',
        required=True,
    )

    # ── Stato ───────────────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ('pending', 'In attesa'),
            ('sent', 'Inviata'),
            ('delivered', 'Consegnata'),
            ('accepted', 'Accettata'),
            ('rejected', 'Scartata'),
            ('error', 'Errore'),
            ('demo', 'Demo'),
        ],
        string='Stato',
        default='pending',
        required=True,
    )

    # ── Identificativi SDI ──────────────────────────────────────────────
    sdi_id = fields.Char(
        string='Identificativo SDI',
        index=True,
    )
    sdi_filename = fields.Char(
        string='Nome file SDI',
    )
    sdi_message_id = fields.Char(
        string='Message-ID PEC',
    )

    # ── Contenuto ───────────────────────────────────────────────────────
    xml_content = fields.Binary(
        string='Contenuto XML',
        attachment=True,
    )
    xml_filename = fields.Char(
        string='Nome file XML',
        compute='_compute_xml_filename',
    )
    raw_pec_content = fields.Text(
        string='Contenuto PEC grezzo',
        help="Email PEC originale per debug.",
    )
    error_message = fields.Text(
        string='Messaggio di errore',
    )

    # ── Display ─────────────────────────────────────────────────────────
    display_name = fields.Char(
        compute='_compute_display_name',
    )

    @api.depends('sdi_filename', 'transaction_type', 'create_date')
    def _compute_display_name(self):
        for rec in self:
            parts = []
            if rec.sdi_filename:
                parts.append(rec.sdi_filename)
            if rec.transaction_type:
                parts.append(dict(rec._fields['transaction_type'].selection).get(
                    rec.transaction_type, rec.transaction_type))
            if rec.create_date:
                parts.append(rec.create_date.strftime('%d/%m/%Y %H:%M'))
            rec.display_name = ' — '.join(parts) if parts else f"Transazione #{rec.id}"

    @api.depends('sdi_filename')
    def _compute_xml_filename(self):
        for rec in self:
            rec.xml_filename = rec.sdi_filename or 'fattura.xml'
