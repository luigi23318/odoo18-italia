{
    'name': 'Odoo 18 - EDI PEC Backend',
    'version': '1.0',
    'summary': 'Send Italian e-invoices via PEC as EDI backend',
    'depends': ['account', 'account_edi', 'l10n_it_edi'],
    'data': [
        'security/ir.model.access.csv',
        'data/edi_format.xml',
        'views/res_company_view.xml',
    ],
    'installable': True,
}
