{
    'name': 'Odoo PEC Fatturazione (Aruba)',
    'version': '1.0',
    'depends': ['account','l10n_it_edi'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_company_view.xml'
    ],
    'installable': True
}
