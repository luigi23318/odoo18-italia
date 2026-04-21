{
    "name": "OdooManager - Sync Dettagli E-Fattura",
    "version": "18.0.3.0.0",
    "category": "Accounting/Localizations/Italy",
    "summary": (
        "Sincronizzazione automatica del tab 'Dettagli e-fattura' "
        "e protezione da modifiche manuali sulle fatture cliente"
    ),
    "description": """
OdooManager - Sync Dettagli E-Fattura (v3.0 - Lock tab)
========================================================

Sincronizza i campi del tab 'Dettagli e-fattura' (aggiunto dal modulo OCA
l10n_it_edi_extension) con le righe reali della fattura cliente.
Protegge le tabelle del tab da modifiche manuali, garantendo coerenza
con le righe contabili reali.

MECCANISMI DI SINCRONIZZAZIONE
------------------------------

1. AUTOMATICA AL CAMBIO RIGHE (@api.onchange)
   Ogni modifica di righe su fattura cliente in bozza triggera il
   ricalcolo. Tab aggiornato in tempo reale.

2. AUTOMATICA ALLA CONFERMA (override _post)
   Safety net al momento della conferma fattura.

3. MANUALE (pulsante "Ricalcola dettagli e-fattura")
   Per forzare il refresh in casi particolari.

PROTEZIONE TABELLE (v3.0)
-------------------------

Il modulo blocca create/write/unlink dei record:
- l10n_it_edi.line (righe e-fattura)
- l10n_it_edi.summary_data (riepilogo aliquote)

sulle fatture CLIENTE (out_invoice, out_refund), tranne quando
l'operazione viene fatta dai meccanismi di sync interni del modulo
(protetti da context flag om_edi_sync_in_progress).

Livelli di protezione:
- Livello Python: intercetta operazioni su ORM
- Livello XML: nasconde pulsanti 'Aggiungi riga' e cestini in UI

Le fatture PASSIVE restano completamente editabili per preservare
la compatibilità con l'import XML di fatture fornitore.

Autore: Luigi Trubiani / OdooManager.cloud
""",
    "author": "Luigi Trubiani / OdooManager.cloud",
    "website": "https://odoomanager.cloud",
    "license": "LGPL-3",
    "depends": [
        "l10n_it_edi_extension",
    ],
    "data": [
        "views/account_move_sync_button.xml",
        "views/lock_edi_tables.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
