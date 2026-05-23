# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Eseguito al primo install del modulo l10n_it_pdcodm.

    Sessione 1: stub. La logica di verifica precondizioni (presenza di
    l10n_it, conteggio voci CEE caricate, ecc.) verrà aggiunta nelle
    sessioni successive man mano che i dati e i modelli saranno
    introdotti (vedi SPEC sezione 12.1 e 17.7).
    """
    _logger.info("Modulo l10n_it_pdcodm installato.")


def pre_uninstall_hook(env):
    """Eseguito prima della disinstallazione del modulo l10n_it_pdcodm.

    Sessione 1: stub. La logica di blocco disinstallazione in presenza
    di scritture su conti del PdC OdooManager verrà aggiunta nella
    sessione 12 (vedi SPEC sezione 12.2 e 17.7).
    """
    _logger.info("Disinstallazione modulo l10n_it_pdcodm in corso.")
