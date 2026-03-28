# -*- coding: utf-8 -*-
# Copyright 2026 OdooManager.cloud
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

"""
Integrazione nel wizard "Invia e Stampa" di Odoo 18.

In Odoo 18 CE, account.move.send è un AbstractModel.
Fare _inherit da TransientModel su un AbstractModel causa:
    TypeError: transforms the abstract model 'account.move.send' into
    a non-abstract model.

Per questo motivo, questo file NON definisce alcun modello.

L'invio PEC è comunque pienamente funzionante tramite:
- Bottone "Invia via PEC" sulla singola fattura (account.move)
- Wizard invio massivo dalla lista fatture (l10n_it_pec.send.wizard)
- Override di _l10n_it_edi_send() nel pipeline EDI nativo

Se una futura versione di Odoo 18 CE renderà account.move.send
un TransientModel concreto, si potrà riabilitare l'integrazione.
"""
