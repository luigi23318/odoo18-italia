{
    'name': 'A-Cube Bridge - Fatturazione Elettronica',
    'version': '18.0.1.1.0',
    'category': 'Accounting/Localizations',
    'summary': 'Integrazione A-Cube API: import fatture estere da PDF con AI',
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
