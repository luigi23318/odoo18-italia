# Part of l10n_it_pdcodm. See LICENSE file for full copyright and licensing details.
{
    'name': "Piano dei Conti Italiano OdooManager",
    'summary': "PdC italiano professionale alternativo a l10n_it standard, con compatibilità export Passepartout",
    'description': """
        Modulo Odoo 18 per la gestione contabile professionale italiana.
        Fornisce un Piano dei Conti completo (~2100 conti) con voci CEE,
        deducibilità IRES/IRAP, regimi multipli e tabella di transcodifica
        per export bilancio verso Passepartout/ADP Bilancio.

        Coesiste con l10n_it standard senza sostituirlo: tasse IVA,
        fatturazione elettronica e configurazioni EDI restano invariate.
        Si attiva per singola company tramite flag dedicato.
    """,
    'author': "OdooManager.cloud",
    'website': "https://www.odoomanager.cloud",
    'license': 'LGPL-3',
    'category': 'Accounting/Localizations/Account Charts',
    'version': '18.0.1.0.0',
    'depends': [
        'account',
        'l10n_it',
    ],
    'data': [
        # security PRIMA (vedi SPEC 17.2)
        'security/pdcodm_security.xml',
        'security/ir.model.access.csv',
        # dati statici
        'data/l10n_it_pdcodm.cee.section.csv',
        # viste: menu root PRIMA, viste che vi appendono figli DOPO
        'views/menus.xml',
        'views/l10n_it_pdcodm_cee_section_views.xml',
        'views/account_account_views.xml',
        'views/wizard_views.xml',
        'views/res_company_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'pre_uninstall_hook': 'pre_uninstall_hook',
}
