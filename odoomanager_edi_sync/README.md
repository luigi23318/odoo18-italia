# OdooManager - Sync Dettagli E-Fattura (v3.0)

1. Copio il modulo da downloads al server VPS ARUBA:

scp -P 59362 -r -i "C:\Users\Utente\Documents\CHIAVE SSH\id_ed25519" odoomanager_edi_sync root@188.213.173.107:/home/odoo/odoo-docker/addons-italia/

2. Permessi

cd /home/odoo/odoo-docker/addons-italia/
find odoomanager_edi_sync -type d -exec chmod 775 {} \;
find odoomanager_edi_sync -type f -exec chmod 664 {} \;

3. Aggiorna da menu app odoo in modalità sviluppatore

4. Verifica versione

App → filtro "Installata" → cerca "odoomanager" → dovresti vedere 18.0.3.0.0.

Modulo OdooManager.cloud che sincronizza automaticamente il tab **"Dettagli e-fattura"** (aggiunto da `l10n_it_edi_extension`) con le righe reali della fattura cliente. Inoltre protegge le tabelle del tab da modifiche manuali sulle fatture cliente, garantendo che i dati siano sempre coerenti con le righe contabili reali.

## Cosa c'è di nuovo nella v3.0

La v2.0 aveva già i 3 meccanismi di sync (onchange + _post + pulsante). La **v3.0 aggiunge la protezione delle tabelle del tab**:

- **Lato Python**: override di `create`/`write`/`unlink` sui modelli `l10n_it_edi.line` e `l10n_it_edi.summary_data`. Qualsiasi tentativo di modifica manuale (da UI, API, RPC) viene bloccato sulle fatture cliente con messaggio di errore chiaro.

- **Lato vista XML**: le tabelle del tab diventano `readonly` sulle fatture cliente. L'utente non vede più il pulsante "Aggiungi riga" né le iconcine cestino.

Il sync interno del modulo continua a funzionare perché usa il context flag `om_edi_sync_in_progress` che bypassa il blocco.

## Comportamento per tipo fattura

| Tipo fattura | Righe/Summary editabili? | Sync automatico? |
|---|---|---|
| **Cliente** (`out_invoice`, `out_refund`) | ❌ No (gestite dal modulo) | ✅ Sì |
| **Fornitore** (`in_invoice`, `in_refund`) | ✅ Sì (import XML) | ❌ No (preservati) |
| Altro | ✅ Sì (non interessate) | ❌ No |

## Aggiornamento da versioni precedenti

Se hai già installato v1.0 o v2.0:

```bash
# 1. Copia la nuova versione sull'host sovrascrivendo
scp -P 59362 -r -i "path_chiave" odoomanager_edi_sync root@IP:/home/odoo/odoo-docker/addons-italia/

# 2. Sistema permessi (se necessario)
cd /home/odoo/odoo-docker/addons-italia/
find odoomanager_edi_sync -type d -exec chmod 775 {} \;
find odoomanager_edi_sync -type f -exec chmod 664 {} \;

# 3. Aggiorna il modulo
docker exec odoo18-app odoo -d odoo18 -u odoomanager_edi_sync --stop-after-init --no-http
docker restart odoo18-app
```

## Installazione da zero

### 1. Copia sul server

```powershell
scp -P 59362 -r -i "C:\path\chiave_ssh" odoomanager_edi_sync root@IP_SERVER:/home/odoo/odoo-docker/addons-italia/
```

### 2. Sistema permessi

```bash
cd /home/odoo/odoo-docker/addons-italia/
find odoomanager_edi_sync -type d -exec chmod 775 {} \;
find odoomanager_edi_sync -type f -exec chmod 664 {} \;
```

### 3. Installa

```bash
docker exec odoo18-app odoo -d odoo18 --update=base --stop-after-init --no-http
docker exec odoo18-app odoo -d odoo18 -i odoomanager_edi_sync --stop-after-init --no-http
docker restart odoo18-app
```

## Test della v3.0

### Test 1 — Lock UI su fattura cliente

1. Apri una fattura cliente in bozza
2. Vai al tab "Dettagli e-fattura"
3. Verifica che **NON** sia più presente:
   - Il pulsante "Aggiungi riga" sotto la tabella righe
   - L'iconcina cestino a fianco delle righe esistenti
   - Stesso per la tabella summary
4. La tabella diventa grigiata/read-only

### Test 2 — Lock da API (simulazione)

Se vuoi testare la protezione Python, lancia in psql:

```sql
-- Non serve. Il test via UI è sufficiente.
-- La protezione Python scatta comunque in caso di tentativi da altre vie.
```

Oppure da shell Odoo:

```bash
docker exec -it odoo18-app odoo shell -d odoo18 --no-http
```

```python
# Prova a cancellare un summary di una fattura cliente
move = env['account.move'].search([('move_type', '=', 'out_invoice')], limit=1)
move.l10n_it_edi_summary_ids.unlink()
# Dovrebbe sollevare UserError con messaggio chiaro
```

### Test 3 — Fattura fornitore resta editabile

1. Apri una fattura fornitore (anche importata da XML)
2. Vai al tab "Dettagli e-fattura"
3. Il pulsante "Aggiungi riga" e i cestini sono ancora presenti
4. Il comportamento è identico a prima dell'installazione del modulo

### Test 4 — Il sync interno funziona

1. Apri una fattura cliente in bozza
2. Aggiungi/modifica una riga prodotto nel tab "Righe fattura"
3. Torna al tab "Dettagli e-fattura"
4. Vedi i dati aggiornati (nonostante il lock, perché il sync usa il context flag di bypass)

## Architettura tecnica

### Context flag `om_edi_sync_in_progress`

È la chiave di tutto. Tutti i metodi interni del modulo che devono scrivere sulle tabelle bloccate:

- `_om_sync_edi_details_silent()`
- `_om_rebuild_edi_lines()`
- `_om_rebuild_edi_summary()`

vengono chiamati con `self.with_context(om_edi_sync_in_progress=True)`. Gli override di `create`/`write`/`unlink` cercano questo flag nel context e, se presente, lasciano passare l'operazione.

### Bypass per superuser

Gli override rispettano `self.env.su` (superuser mode). Durante installazione/aggiornamento del modulo tramite `-i` o `-u`, Odoo gira come superuser e le operazioni di demo data o migrazione passano senza blocchi.

### Struttura del modulo

```
odoomanager_edi_sync/
├── __init__.py
├── __manifest__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── account_move.py              # Meccanismi sync + pulsante
│   ├── l10n_it_edi_line.py          # Lock righe tab (v3.0)
│   └── l10n_it_edi_summary_data.py  # Lock summary tab (v3.0)
└── views/
    ├── account_move_sync_button.xml # Pulsante manuale
    └── lock_edi_tables.xml          # Lock UI tabelle (v3.0)
```

## Disinstallazione

```bash
docker exec odoo18-app odoo -d odoo18 --uninstall odoomanager_edi_sync --stop-after-init --no-http
```

Dopo la disinstallazione:
- Il tab "Dettagli e-fattura" torna completamente editabile sulle fatture cliente
- I meccanismi di sync automatico vengono rimossi
- Il pulsante manuale sparisce
- I dati esistenti nelle tabelle restano nel database

## Autore

Luigi Trubiani — OdooManager.cloud

Licenza: LGPL-3
