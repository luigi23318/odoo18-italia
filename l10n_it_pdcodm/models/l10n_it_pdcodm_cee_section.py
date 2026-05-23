# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class L10nItPdcodmCeeSection(models.Model):
    """Voce CEE per riclassificazione del bilancio civilistico italiano.

    Le 204 voci sono caricate da data/l10n_it_pdcodm.cee.section.csv e
    derivano dalla tassonomia XBRL ITCC, allineata agli artt. 2424/2425
    del Codice Civile. Sono dati di sistema: l'utente le consulta in
    sola lettura; solo l'Administrator può modificarne/aggiungerne.
    """
    _name = 'l10n_it_pdcodm.cee.section'
    _description = "Voce CEE per riclassificazione bilancio italiano"
    _order = 'code'
    _rec_name = 'code'
    _rec_names_search = ['code', 'description']

    code = fields.Char(
        string="Codice CEE",
        required=True,
        index=True,
    )
    description = fields.Text(
        string="Descrizione voce",
        required=True,
    )
    section = fields.Selection(
        selection=[
            ('SP_ATT_A', "SP Attivo - A) Crediti verso soci"),
            ('SP_ATT_BI', "SP Attivo - B.I) Immobilizzazioni immateriali"),
            ('SP_ATT_BII', "SP Attivo - B.II) Immobilizzazioni materiali"),
            ('SP_ATT_BIII', "SP Attivo - B.III) Immobilizzazioni finanziarie"),
            ('SP_ATT_CI', "SP Attivo - C.I) Rimanenze"),
            ('SP_ATT_CII', "SP Attivo - C.II) Crediti"),
            ('SP_ATT_CIII', "SP Attivo - C.III) Attività finanziarie non immobilizzate"),
            ('SP_ATT_CIV', "SP Attivo - C.IV) Disponibilità liquide"),
            ('SP_ATT_D', "SP Attivo - D) Ratei e risconti attivi"),
            ('SP_PAS_A', "SP Passivo - A) Patrimonio netto"),
            ('SP_PAS_B', "SP Passivo - B) Fondi per rischi e oneri"),
            ('SP_PAS_C', "SP Passivo - C) TFR"),
            ('SP_PAS_D', "SP Passivo - D) Debiti"),
            ('SP_PAS_E', "SP Passivo - E) Ratei e risconti passivi"),
            ('CE_A', "CE - A) Valore della produzione"),
            ('CE_B', "CE - B) Costi della produzione"),
            ('CE_C', "CE - C) Proventi e oneri finanziari"),
            ('CE_D', "CE - D) Rettifiche di valore"),
            ('CE_20', "CE - 20) Imposte sul reddito"),
        ],
        string="Sezione di bilancio",
        required=True,
    )
    statement = fields.Selection(
        selection=[
            ('Stato Patrimoniale', "Stato Patrimoniale"),
            ('Conto Economico', "Conto Economico"),
            ('Altro', "Altro"),
        ],
        string="Prospetto",
    )
    side = fields.Char(
        string="Lato",
    )

    _sql_constraints = [
        ('code_uniq', 'unique(code)', "Il codice voce CEE deve essere unico."),
    ]

    @api.depends('code', 'description')
    def _compute_display_name(self):
        for rec in self:
            desc = (rec.description or '').split('\n')[0]
            if len(desc) > 80:
                desc = desc[:77] + '...'
            rec.display_name = "%s — %s" % (rec.code or '', desc) if desc else (rec.code or '')
