# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

{
    'name': 'Italia - Fatturazione Elettronica via PEC',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Localizations/EDI',
    'summary': 'Invio FatturaPA allo SDI tramite PEC (backend EDI alternativo)',
    'description': """
Modulo per l'invio della fatturazione elettronica italiana (FatturaPA)
allo SDI tramite PEC, integrato nativamente nel flusso EDI di Odoo 18.

Architettura Opzione C (ibrida):
- PEC diventa un backend EDI alternativo, NON un sistema parallelo
- L'XML FatturaPA viene generato dal motore standard l10n_it_edi
- Solo il trasporto cambia: PEC invece del web service Odoo/proxy
- Gli stati restano quelli standard di account.move (l10n_it_edi_state)
- Le notifiche SDI di ritorno vengono lette via IMAP e mappate sugli stati standard
- Supporto modalità: demo (dry-run), test, produzione

Funzionalità:
- Invio fatture attive via PEC allo SDI
- Ricezione e parsing notifiche SDI (RC, NS, MC, AT, NE, DT)
- Ricezione fatture passive via PEC
- Cron job per polling inbox PEC
- Integrazione nel wizard "Invia e Stampa" di Odoo 18
- Log completo nel Chatter della fattura
- Dry-run mode per test senza invio reale
    """,
    'author': 'OdooManager.cloud',
    'website': 'https://odoomanager.cloud',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_it_edi',
        'mail',
    ],
    'data': [
        'security/res_groups.xml',
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/res_company_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'wizard/pec_send_wizard_views.xml',
        'wizard/pec_upload_signed_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
