# -*- coding: utf-8 -*-
{
    'name': "Italian E-invoice Withholding - Bug Fixes",
    'summary': (
        "Workaround temporaneo per bug noti di l10n_it_edi_withholding. "
        "Si auto-disattiva quando i bug saranno corretti upstream."
    ),
    'description': """
Italian E-invoice Withholding - Bug Fixes
==========================================

Questo modulo raccoglie workaround temporanei per bug noti del modulo
``l10n_it_edi_withholding`` di Odoo S.A. relativi alla generazione
del file XML FatturaPA in presenza di ritenute d'acconto.

Replica concettualmente la funzione storica del modulo OCA
``l10n_it_fatturapa_out_wt`` (versioni 8.0-16.0), che corregge i
bug della generazione XML quando ci sono ritenute. Il modulo OCA
non è disponibile per Odoo 18 e non è compatibile con il modulo
standard ``l10n_it_edi`` di Odoo S.A.

Filosofia di progettazione
--------------------------

* **Auto-disattivante**: ogni fix interviene solo se rileva una
  discrepanza effettiva tra il valore calcolato e il valore atteso.
  Quando Odoo S.A. correggerà i bug upstream, i fix non interverranno
  più automaticamente, senza necessità di disinstallare il modulo.

* **Diagnostico**: ogni invocazione produce log a livello INFO che
  documentano se il fix è intervenuto o meno, con i valori in gioco.

* **Mirato**: ogni fix è una funzione separata con scope ben definito.
  Non si replicano funzionalità che già funzionano correttamente in
  ``l10n_it_edi_withholding``.

* **Estensibile**: la struttura permette di aggiungere nuovi fix
  semplicemente creando nuove funzioni e chiamandole nell'override.

Bug coperti attualmente
-----------------------

1. **ImportoTotaleDocumento errato in presenza di ritenute**

   Il modulo ``l10n_it_edi_withholding`` genera ``<ImportoTotaleDocumento>``
   usando ``amount_total`` (netto ritenute), ma la specifica FatturaPA
   1.6.1 e le FAQ dell'Agenzia delle Entrate richiedono il lordo
   ritenute (cioè il totale prima di sottrarre le ritenute d'acconto).

   Il fix usa il campo ``l10n_it_amount_before_withholding_signed``
   già calcolato dal modulo standard per popolare correttamente il
   tag XML.

   Riferimento normativo:
     - Agenzia Entrate, FAQ 21/12/2018 e seguenti
     - Specifica tecnica FatturaPA 1.6.1, paragrafo 2.1.1.9

   Esempio: agente forfettario, provvigione 1000€, IVA 0% (N2.2),
   ENASARCO -8.5%.
     - Atteso: ``<ImportoTotaleDocumento>1000.00</ImportoTotaleDocumento>``
     - Bug:    ``<ImportoTotaleDocumento>915.00</ImportoTotaleDocumento>``

Compatibilità con fix futuri di Odoo S.A.
------------------------------------------

Il fix verifica la presenza di una discrepanza prima di intervenire.
Se Odoo S.A. correggerà il bug nel codice upstream, il valore
calcolato dal ``super()`` sarà già corretto, la discrepanza sarà
zero, e il fix non modificherà nulla.

In tal caso si può comunque disinstallare il modulo per pulizia,
ma non è strettamente necessario.
    """,
    'version': '18.0.1.0.0',
    'category': 'Accounting/Localizations/EDI',
    'author': "Luigi Trubiani / OdooManager.cloud",
    'website': "https://odoomanager.cloud",
    'license': 'AGPL-3',
    'depends': [
        'l10n_it_edi_withholding',
    ],
    'data': [],
    'auto_install': False,
    'installable': True,
    'application': False,
}
