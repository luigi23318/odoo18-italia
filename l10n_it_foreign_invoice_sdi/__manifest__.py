{
    'name': 'Fatture Estere Passive - Integrazione SDI',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Gestione fatture estere passive con invio SDI via Aruba Premium',
    'description': """
Modulo per la gestione delle fatture estere passive (TD17/TD18/TD19).

Funzionalita:
- Upload PDF fattura estera (singolo o batch)
- Doppio motore di estrazione: Tesseract OCR locale / A-Cube API cloud
- Revisione obbligatoria operatore
- Generazione XML FatturaPA v1.2.3
- Validazione XSD
- Invio SDI via Aruba Fatturazione Elettronica Premium API
- Tracking notifiche SDI
- Registrazione contabile con reverse charge
- Download XML singolo o ZIP batch
    """,
    'author': 'Custom Development',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['account', 'l10n_it'],
    'data': [
        'security/foreign_invoice_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'report/batch_control_report.xml',
        'views/foreign_invoice_import_views.xml',
        'views/foreign_invoice_batch_views.xml',
        'views/res_config_settings_views.xml',
        'views/menuitems.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'external_dependencies': {
        'python': ['pdfplumber', 'lxml'],
    },
}
