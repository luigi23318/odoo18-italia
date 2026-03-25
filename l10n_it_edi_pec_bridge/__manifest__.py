# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Italia - Fatturazione Elettronica via PEC',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Localizations/EDI',
    'summary': 'Invio e ricezione fatture elettroniche SDI tramite PEC per Odoo Community',
    'description': """
Modulo ponte per la fatturazione elettronica italiana via PEC
=============================================================

Questo modulo estende l10n_it_edi (standard Odoo) aggiungendo il canale
di trasmissione PEC per l'invio e la ricezione delle fatture elettroniche
al Sistema di Interscambio (SDI) dell'Agenzia delle Entrate.

**Funzionalità principali:**

* Invio automatico fatture attive a SDI via PEC
* Ricezione automatica notifiche SDI (RC, NS, MC, NE, AT)
* Importazione automatica fatture passive da SDI
* Gestione stati SDI sulla fattura
* Modalità Demo per test senza invio reale
* Modalità Validazione per verifica XML con download per portale AdE
* Pulizia automatica casella PEC con ritardo configurabile
* Invio massivo fatture
* Hook di disinstallazione per pulizia allegati demo/validazione

**Requisiti:**
* Casella PEC dedicata alla fatturazione elettronica
* Registrazione PEC su portale AdE come indirizzo telematico

**Compatibile con:** Odoo 18 Community Edition + moduli OCA l10n-italy
    """,
    'author': 'Luigi Sai',
    'website': 'https://odoomanager.cloud',
    'license': 'LGPL-3',
    'depends': [
        'l10n_it_edi',
        'account',
        'mail',
        'fetchmail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/sdi_pec_transaction_views.xml',
        'views/menu.xml',
        'wizards/send_to_sdi_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'uninstall_hook': '_uninstall_hook',
}
