{
    'name': 'A-Cube Bridge - Fatturazione Elettronica',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Integrazione A-Cube API: import fatture estere da PDF con AI, fatturazione elettronica SDI',
    'description': """
        Modulo di integrazione con le API A-Cube (acubeapi.com) per Odoo 18 CE.

        Funzionalità Fase 1:
        - Autenticazione JWT con sandbox/produzione A-Cube
        - Import fatture estere da PDF tramite AI (Invoice Extract)
        - Conversione automatica PDF → XML FatturaPA
        - Conversione importi in EUR con tasso Banca d'Italia
        - Creazione automatica fattura fornitore in bozza
        - Salvataggio PDF originale e XML come allegati

        Fasi successive (da sviluppare):
        - Invio fatture attive al SDI
        - Ricezione fatture passive dal SDI
        - Notifiche SDI
        - Open Banking PSD2
    """,
    'author': 'OdooManager',
    'website': 'https://odoomanager.cloud',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_it',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/acube_wizard_views.xml',
    ],
    'external_dependencies': {
        'python': ['requests', 'lxml'],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
