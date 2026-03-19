# A-Cube Bridge - Fatturazione Elettronica per Odoo 18 CE

## Descrizione

Modulo Odoo 18 Community Edition per l'integrazione con le API A-Cube (acubeapi.com).

### Funzionalità attuali (Fase 1)

- **Import fatture estere da PDF**: carica un PDF di una fattura estera, l'AI di A-Cube estrae i dati e crea automaticamente una bozza di fattura fornitore in Odoo
- Conversione automatica degli importi in EUR con tasso di cambio Banca d'Italia
- Salvataggio PDF originale e XML FatturaPA come allegati
- Configurazione sandbox/produzione nelle impostazioni

### Funzionalità future

- Invio fatture attive al SDI (ciclo attivo)
- Ricezione fatture passive dal SDI (ciclo passivo)
- Gestione notifiche SDI
- Open Banking PSD2 (movimenti bancari)

## Requisiti

- Odoo 18 Community Edition
- Localizzazione italiana (`l10n_it`)
- Account A-Cube (registrazione gratuita per sandbox su acubeapi.com)
- Per Invoice Extract: attivazione specifica in sandbox (scrivere a business@a-cube.io)

## Installazione

1. Copia la cartella `l10n_it_acube_bridge` nella directory degli addons custom di Odoo
2. Aggiorna la lista moduli: Impostazioni → Aggiornamento moduli
3. Cerca "A-Cube Bridge" nelle App e clicca Installa

## Configurazione

1. Vai in **Impostazioni → Contabilità → A-Cube Bridge**
2. Seleziona l'ambiente (Sandbox per test)
3. Inserisci email e password del tuo account A-Cube
4. Clicca **Testa Connessione** per verificare

## Utilizzo: Import fattura estera da PDF

1. Vai in **Contabilità → Fornitori → Importa fattura estera da PDF**
2. Carica il PDF della fattura
3. Opzionalmente modifica l'aliquota IVA default e l'opzione di conversione EUR
4. Clicca **Carica e Analizza con AI**
5. Attendi l'elaborazione (10-30 secondi)
6. Rivedi e correggi i dati estratti dall'AI
7. **Seleziona il Tipo Documento** (TD17/TD18/TD19 per autofatture — l'AI non lo determina)
8. Clicca **Crea Fattura Fornitore**
9. La fattura viene creata in bozza con PDF e XML come allegati

## Autore

OdooManager - https://odoomanager.cloud

## Licenza

LGPL-3
