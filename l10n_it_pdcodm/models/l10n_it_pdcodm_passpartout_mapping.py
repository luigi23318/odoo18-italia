# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class L10nItPdcodmPasspartoutMapping(models.Model):
    """Tabella di transcodifica conto OdooManager <-> Passepartout (SPEC 4.4).

    Dato di interoperabilità per facilitare l'import in
    Passepartout/ADP Bilancio del saldo dei conti del PdC OdooManager.
    NON è una replica del database Passepartout: è una mappa di
    corrispondenza funzionale (vedi SPEC 14.3).

    Le 2121 righe sono caricate dal CSV
    `data/l10n_it_pdcodm.passpartout.mapping.csv` all'installazione del
    modulo. L'utente Administrator può personalizzare singoli mapping
    per la propria company (campo opzionale `company_id`).
    """
    _name = 'l10n_it_pdcodm.passpartout.mapping'
    _description = "Transcodifica conto OdooManager <-> Passepartout"
    _order = 'pdcodm_code'
    _rec_name = 'pdcodm_code'
    _rec_names_search = ['pdcodm_code', 'pdcodm_name', 'passpartout_code']

    pdcodm_code = fields.Char(
        string="Codice OdooManager",
        required=True,
        index=True,
        help="Codice del conto nel PdC OdooManager (formato 6 cifre XYYZZZ).",
    )
    pdcodm_name = fields.Char(
        string="Descrizione OdooManager",
        help="Descrizione del conto OdooManager (riferimento; non vincolata "
             "al nome attuale del conto sulla company).",
    )
    passpartout_code = fields.Char(
        string="Codice Passepartout",
        required=True,
        help="Codice del conto Passepartout corrispondente, nel formato "
             "tradizionale XXX.NNNNN (es. 208.00241).",
    )
    passpartout_name = fields.Char(
        string="Descrizione Passepartout",
        help="Descrizione originale Passepartout (tipicamente in MAIUSCOLO).",
    )
    cee_code = fields.Char(
        string="Codice CEE",
        index=True,
        help="Voce CEE comune ai due conti, per riferimento incrociato.",
    )
    mapping_type = fields.Selection(
        selection=[
            ('1:1', "1:1 (corrispondenza diretta)"),
            ('N:1', "N:1 (più conti OdooManager su un solo Passepartout)"),
            ('1:N', "1:N (un conto OdooManager su più Passepartout)"),
        ],
        string="Tipo mapping",
        default='1:1',
        required=True,
    )
    notes = fields.Text(
        string="Note",
        help="Note per casi speciali (es. mapping condizionato dal regime "
             "fiscale, eccezioni note, riferimenti normativi).",
    )
    company_id = fields.Many2one(
        'res.company',
        string="Azienda (personalizzazione)",
        help="Lasciare vuoto per il mapping standard valido per tutte le "
             "company. Valorizzare solo per personalizzazioni company-specific "
             "che sovrascrivono il mapping standard.",
    )

    _sql_constraints = [
        (
            'mapping_uniq',
            'unique(pdcodm_code, company_id)',
            "Esiste già un mapping per questo codice OdooManager e azienda.",
        ),
    ]
