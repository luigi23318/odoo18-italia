# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import logging

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Eseguito al primo install del modulo l10n_it_pdcodm.

    Esegue 3 verifiche di stato (non bloccanti):
    1. Presenza del modulo `l10n_it` (dipendenza, dovrebbe esserci
       comunque vista la dichiarazione nel manifest).
    2. Caricamento delle 204 voci CEE.
    3. Registrazione del chart template `it_pdcodm` nel mapping Odoo.

    Eventuali anomalie sono loggate come warning ma non bloccano
    l'installazione: l'admin tecnico può controllare a mano.
    Vedi SPEC 12.1.
    """
    _logger.info("Modulo l10n_it_pdcodm installato.")

    # (1) Verifica dipendenza l10n_it (chart template generic deve esistere)
    if not env.ref('l10n_it.l10n_chart_it_generic', raise_if_not_found=False):
        _logger.warning(
            "l10n_it base chart template (l10n_it.l10n_chart_it_generic) "
            "non trovato. Il PdC OdooManager dovrebbe funzionare comunque, "
            "ma `l10n_it` è dichiarato come dipendenza nel manifest."
        )

    # (2) Tabella voci CEE
    cee_count = env['l10n_it_pdcodm.cee.section'].search_count([])
    if cee_count < 200:
        _logger.warning(
            "Tabella voci CEE incompleta: solo %d voci caricate "
            "(attese ~204). Verificare il caricamento del CSV "
            "data/l10n_it_pdcodm.cee.section.csv.",
            cee_count,
        )
    else:
        _logger.info("Tabella voci CEE: %d record caricati.", cee_count)

    # (3) Chart template registrato
    try:
        mapping = env['account.chart.template']._get_chart_template_mapping(get_all=True)
        if 'it_pdcodm' not in mapping:
            _logger.warning(
                "Chart template 'it_pdcodm' non registrato nel mapping Odoo. "
                "Verificare il file models/template_l10n_it_pdcodm.py e che "
                "il modulo abbia category='Accounting/Localizations/Account Charts'."
            )
        else:
            _logger.info("Chart template 'it_pdcodm' registrato correttamente.")
    except Exception as e:
        _logger.warning(
            "Impossibile verificare la registrazione del chart template: %s", e
        )

    # (4) Tabella transcodifica Passepartout
    mapping_count = env['l10n_it_pdcodm.passpartout.mapping'].search_count([])
    if mapping_count < 2000:
        _logger.warning(
            "Tabella transcodifica Passepartout incompleta: solo %d mapping "
            "caricati (attesi ~2121).",
            mapping_count,
        )


def pre_uninstall_hook(env):
    """Eseguito prima della disinstallazione del modulo l10n_it_pdcodm.

    Blocca la disinstallazione se esistono scritture contabili su conti
    `origin='standard'` del PdC OdooManager (SPEC 12.2). Disinstallare
    in presenza di scritture causerebbe la perdita di tracciabilità dei
    riferimenti contabili.

    Per disinstallare comunque (caso di emergenza), l'admin tecnico
    deve prima:
    - Disinstallare il PdC su ogni company OdooManager (wizard Sessione 7), oppure
    - Eliminare manualmente le scritture residue via shell.
    """
    # NB: il check usa una query SQL diretta per efficienza e per non
    # dipendere dall'ACL dell'utente che disinstalla.
    env.cr.execute("""
        SELECT COUNT(DISTINCT m.id)
        FROM account_move m
        JOIN account_move_line ml ON ml.move_id = m.id
        JOIN account_account a ON a.id = ml.account_id
        WHERE a.l10n_it_pdcodm_origin = 'standard'
    """)
    move_count = env.cr.fetchone()[0] or 0

    if move_count > 0:
        raise UserError(_(
            "Impossibile disinstallare l10n_it_pdcodm.\n\n"
            "Sono presenti %(count)d scritture contabili su conti del "
            "Piano dei Conti OdooManager (origin='standard'), "
            "distribuite su una o più aziende.\n\n"
            "Disinstallare il modulo causerebbe la perdita di "
            "tracciabilità dei riferimenti contabili (CEE, deducibilità, "
            "regime). Per disinstallare correttamente:\n"
            "  1. Su ogni azienda con PdC OdooManager attivo, lancia il "
            "wizard \"Disinstalla PdC OdooManager\" (questo è permesso "
            "solo su aziende senza scritture, quindi se hai scritture "
            "devi prima crearne una nuova azienda).\n"
            "  2. Quando nessuna azienda ha più PdC OdooManager attivo, "
            "ripeti la disinstallazione del modulo."
        ) % {'count': move_count})

    _logger.info("Disinstallazione modulo l10n_it_pdcodm in corso (nessuna scrittura su conti PdC).")
