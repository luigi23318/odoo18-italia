# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import base64
import csv
import io
import logging
import zipfile

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Mappa account_type Odoo → sezione di bilancio per export Passepartout
# (SPEC 9.2: "Attività", "Passività", "Costi", "Ricavi", ecc.)
_ACCOUNT_TYPE_TO_SEZIONE = {
    'asset_receivable': 'Attività',
    'asset_cash': 'Attività',
    'asset_current': 'Attività',
    'asset_non_current': 'Attività',
    'asset_prepayments': 'Attività',
    'asset_fixed': 'Attività',
    'liability_payable': 'Passività',
    'liability_credit_card': 'Passività',
    'liability_current': 'Passività',
    'liability_non_current': 'Passività',
    'equity': 'Patrimonio Netto',
    'equity_unaffected': 'Patrimonio Netto',
    'income': 'Ricavi',
    'income_other': 'Ricavi',
    'expense': 'Costi',
    'expense_direct_cost': 'Costi',
    'expense_depreciation': 'Costi',
    'off_balance': "Conti d'Ordine",
}


class PdcodmExportPasspartoutWizard(models.TransientModel):
    """Wizard "Esporta bilancio Passepartout" (SPEC 7.3, 9).

    Genera 2 file CSV scaricabili per il commercialista:
    - `bilancio_saldi.csv`: saldi conti del periodo selezionato
    - `mapping_conti.csv`: tabella di transcodifica per facilitare
      l'abbinamento iniziale in Passepartout/ADP Bilancio.

    I 2 file vengono compressi in un singolo ZIP allegato al record
    wizard, e l'utente scarica via URL.
    """
    _name = 'l10n_it_pdcodm.export.passpartout.wizard'
    _description = "Wizard esportazione bilancio per Passepartout"

    company_id = fields.Many2one(
        'res.company',
        string="Azienda",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    date_from = fields.Date(
        string="Data inizio",
        required=True,
        default=lambda self: fields.Date.today().replace(month=1, day=1),
    )
    date_to = fields.Date(
        string="Data fine",
        required=True,
        default=lambda self: fields.Date.today().replace(month=12, day=31),
    )
    export_type = fields.Selection(
        selection=[
            ('annual', "Saldi annuali"),
            ('periodic', "Saldi periodici"),
        ],
        string="Tipo export",
        default='annual',
        required=True,
        help="`Saldi annuali`: per chiusura esercizio (anno fiscale completo). "
             "`Saldi periodici`: per saldi infra-anno (es. trimestre, semestre).",
    )
    include_zero_balance = fields.Boolean(
        string="Includi conti con saldo zero",
        default=False,
        help="Se attivo, esporta anche i conti che non hanno avuto "
             "movimentazioni nel periodo (saldi tutti a zero).",
    )

    state = fields.Selection(
        selection=[('form', "Configurazione"), ('done', "Export completato")],
        default='form',
        required=True,
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string="ZIP generato",
        readonly=True,
    )
    n_accounts_exported = fields.Integer(readonly=True)
    n_mappings_exported = fields.Integer(readonly=True)

    def _reopen_self(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for w in self:
            if w.date_from and w.date_to and w.date_from > w.date_to:
                raise UserError(_(
                    "La data inizio (%(from)s) non può essere successiva "
                    "alla data fine (%(to)s)."
                ) % {'from': w.date_from, 'to': w.date_to})

    def action_export(self):
        """Genera i 2 CSV, li zippa, e ritorna un'action di download."""
        self.ensure_one()
        company = self.company_id

        if not company.l10n_it_pdcodm_enabled:
            raise UserError(_(
                "L'azienda %(company)s non ha il PdC OdooManager attivo. "
                "L'export richiede il PdC OdooManager (per i codici CEE "
                "e i mapping Passepartout)."
            ) % {'company': company.name})

        # 1. Genera bilancio_saldi.csv
        saldi_csv, n_accounts = self._generate_saldi_csv(company)

        # 2. Genera mapping_conti.csv
        mapping_csv, n_mappings = self._generate_mapping_csv(company)

        # 3. Zippa
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"bilancio_saldi_{company.name}_{self.date_from}_{self.date_to}.csv",
                saldi_csv.encode('utf-8'),
            )
            zf.writestr(
                f"mapping_conti_{company.name}.csv",
                mapping_csv.encode('utf-8'),
            )
        zip_data = buffer.getvalue()

        # 4. Crea attachment
        attach = self.env['ir.attachment'].create({
            'name': f"export_passpartout_{company.name}_{self.date_to}.zip",
            'datas': base64.b64encode(zip_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/zip',
        })

        # 5. Aggiorna wizard
        self.write({
            'state': 'done',
            'attachment_id': attach.id,
            'n_accounts_exported': n_accounts,
            'n_mappings_exported': n_mappings,
        })

        _logger.info(
            "PdC OdooManager: export Passepartout per company '%s' "
            "(%s → %s): %d conti, %d mapping.",
            company.name, self.date_from, self.date_to, n_accounts, n_mappings,
        )
        return self._reopen_self()

    def _generate_saldi_csv(self, company):
        """Genera il CSV dei saldi conti per il periodo (SPEC 9.2)."""
        MoveLine = self.env['account.move.line'].sudo()
        Account = self.env['account.account'].sudo()
        Mapping = self.env['l10n_it_pdcodm.passpartout.mapping'].sudo()

        base_domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
        ]

        # Saldi del periodo (debit, credit, balance)
        period_groups = MoveLine._read_group(
            domain=base_domain + [
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ],
            groupby=['account_id'],
            aggregates=['debit:sum', 'credit:sum'],
        )
        period_by_account = {acc.id: (debit, credit) for acc, debit, credit in period_groups}

        # Saldo iniziale (cumulato prima di date_from)
        initial_groups = MoveLine._read_group(
            domain=base_domain + [('date', '<', self.date_from)],
            groupby=['account_id'],
            aggregates=['balance:sum'],
        )
        initial_by_account = {acc.id: bal for acc, bal in initial_groups}

        # Saldo finale (cumulato fino a date_to)
        final_groups = MoveLine._read_group(
            domain=base_domain + [('date', '<=', self.date_to)],
            groupby=['account_id'],
            aggregates=['balance:sum'],
        )
        final_by_account = {acc.id: bal for acc, bal in final_groups}

        # Conti del PdC OdooManager (escludo i deprecated se include_zero_balance=False)
        accounts = Account.search([
            ('company_ids', 'in', company.id),
            ('l10n_it_pdcodm_origin', 'in', ('standard', 'user')),
        ])
        # Pre-carico i mapping Passepartout per lookup veloce
        mappings = Mapping.search([
            '|',
            ('company_id', '=', company.id),
            ('company_id', '=', False),
        ])
        # Custom company-specific mappings hanno priorità su quelli standard
        mapping_by_code = {}
        for m in mappings.sorted(key=lambda r: (r.pdcodm_code, r.company_id and 0 or 1)):
            mapping_by_code.setdefault(m.pdcodm_code, m)

        # Costruisco il CSV in memoria
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([
            'codice_pdcodm', 'descrizione',
            'codice_cee_dare', 'codice_cee_avere',
            'sezione_bilancio',
            'saldo_dare', 'saldo_avere',
            'saldo_iniziale', 'saldo_finale',
            'codice_passpartout',
        ])

        n_exported = 0
        for acc in accounts.with_company(company):
            debit, credit = period_by_account.get(acc.id, (0.0, 0.0))
            saldo_iniziale = initial_by_account.get(acc.id, 0.0)
            saldo_finale = final_by_account.get(acc.id, 0.0)

            if not self.include_zero_balance and not (debit or credit or saldo_iniziale or saldo_finale):
                continue

            cee = acc.l10n_it_pdcodm_cee_code or ''
            mapping = mapping_by_code.get(acc.code)
            pp_code = mapping.passpartout_code if mapping else ''
            sezione = _ACCOUNT_TYPE_TO_SEZIONE.get(acc.account_type, '')

            writer.writerow([
                acc.code,
                acc.name,
                cee,  # CEE dare = CEE avere (semplificazione SPEC 9.2)
                cee,
                sezione,
                round(debit, 2),
                round(credit, 2),
                round(saldo_iniziale, 2),
                round(saldo_finale, 2),
                pp_code,
            ])
            n_exported += 1

        return output.getvalue(), n_exported

    def _generate_mapping_csv(self, company):
        """Genera il CSV di transcodifica (SPEC 9.3)."""
        Mapping = self.env['l10n_it_pdcodm.passpartout.mapping'].sudo()
        # Custom company hanno priorità su standard (stesso pdcodm_code)
        mappings = Mapping.search([
            '|',
            ('company_id', '=', company.id),
            ('company_id', '=', False),
        ])
        rows_by_code = {}
        for m in mappings.sorted(key=lambda r: (r.pdcodm_code, r.company_id and 0 or 1)):
            rows_by_code.setdefault(m.pdcodm_code, m)

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([
            'pdcodm_code', 'pdcodm_name',
            'passpartout_code', 'passpartout_name',
            'cee_code', 'mapping_type',
        ])
        for code in sorted(rows_by_code):
            m = rows_by_code[code]
            writer.writerow([
                m.pdcodm_code, m.pdcodm_name or '',
                m.passpartout_code, m.passpartout_name or '',
                m.cee_code or '', m.mapping_type,
            ])
        return output.getvalue(), len(rows_by_code)

    def action_download(self):
        """Ritorna un'action di download dell'attachment ZIP."""
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("Nessun file generato. Esegui prima l'export."))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=true',
            'target': 'self',
        }

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
