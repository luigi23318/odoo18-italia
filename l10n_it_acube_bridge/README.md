# A-Cube Bridge - Fatturazione Elettronica per Odoo 18 CE

## Funzionalità

### Import fattura singola da PDF
Menu: **Contabilità → Fornitori → Importa fattura estera da PDF**

Carica un PDF, l'AI lo analizza, rivedi i dati, crea la fattura fornitore.

### Import batch da PDF
Menu: **Contabilità → Fornitori → Importa fatture estere da PDF (batch)**

Due modalità:
- **File multipli**: aggiungi più PDF uno alla volta nella lista
- **File ZIP**: carica un unico ZIP contenente tutti i PDF

Ogni PDF viene elaborato in sequenza. Le fatture fornitore vengono create automaticamente in bozza. Al termine vedi il riepilogo con successi ed errori.

### Nomi file allegati
Per ogni fattura creata vengono salvati due allegati:
- Il PDF originale con il nome originale (es. `Rechnung-4521.pdf`)
- L'XML FatturaPA con lo stesso nome e estensione .xml (es. `Rechnung-4521.xml`)

## Configurazione

1. **Impostazioni → Contabilità → A-Cube Bridge**
2. Ambiente: Sandbox (per test) o Produzione
3. Email e password del tuo account A-Cube
4. Clicca "Testa Connessione"

## Requisiti

- Odoo 18 Community Edition
- Localizzazione italiana (`l10n_it`)
- Account A-Cube sandbox: https://www.acubeapi.com/servizi/ambiente-sandbox
- Invoice Extract: scrivere a business@a-cube.io per attivazione (10 test gratuiti)

## Licenza

LGPL-3 — OdooManager (https://odoomanager.cloud)
