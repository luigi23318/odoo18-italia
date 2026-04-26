# OdooManager - Sync Dettagli E-Fattura
## Memoria tecnica per sviluppi futuri

**Versione modulo documentata:** 18.0.3.0.0
**Target Odoo:** 18 CE
**Autore originale:** Luigi Trubiani — OdooManager.cloud
**Ultima revisione:** Aprile 2026

---

## ⚠️ WARNING CRITICO PER SVILUPPI FUTURI — Cassa Previdenziale

> **Questo è un bug noto della versione 18.0.3.0.0 che deve essere risolto.**
>
> Il metodo `_om_filter_iva_taxes()` in `models/account_move.py` include erroneamente la Cassa Previdenziale tra le imposte IVA quando popola il campo `tax_rate` del summary.
>
> **Causa tecnica:**
>
> ```python
> def _om_filter_iva_taxes(self, taxes):
>     return taxes.filtered(
>         lambda t: t.l10n_it_exempt_reason
>         or (t.amount > 0 and t.amount_type == "percent")
>     )
> ```
>
> Il filtro `amount > 0 and amount_type == "percent"` include sia IVA ordinaria (es. 22%) **sia Cassa Previdenziale 4%**, perché entrambe sono `percent` con amount > 0.
>
> **Impatto sulle fatture di professionisti con Cassa Previdenziale:**
> - Fattura forfettaria (N2.2) con imposta "0% Forfettario" + "Cassa Previdenza 4%"
> - Il metodo prende la prima imposta IVA trovata (`iva_taxes[0]`), che può essere la Cassa se nella tax_ids viene prima
> - Il summary può finire con `tax_rate=4, non_taxable_nature=False` invece di `tax_rate=0, non_taxable_nature="N2.2"`
>
> **Impatto SDI:** Nessuno. L'XML è generato dal core Odoo, non dai campi del tab. La Cassa finisce correttamente in `<DatiCassaPrevidenziale>`.
>
> **Soluzione proposta per v18.0.4.0.0:**
>
> Rifinire il filtro per escludere esplicitamente la Cassa Previdenziale. Possibili approcci:
>
> 1. **Check sul tax_group_id:** le imposte "vere IVA" in Odoo Italia hanno `tax_group_id` specifici. Cassa Previdenziale ha tax_group diverso.
>    ```python
>    return taxes.filtered(
>        lambda t: t.l10n_it_exempt_reason
>        or (t.amount > 0 and t.amount_type == "percent"
>            and 'iva' in (t.tax_group_id.name or '').lower())
>    )
>    ```
>
> 2. **Check sul campo `l10n_it_pension_fund_type`** (se installato `l10n_it_edi_withholding`):
>    ```python
>    return taxes.filtered(
>        lambda t: t.l10n_it_exempt_reason
>        or (t.amount > 0 and t.amount_type == "percent"
>            and not getattr(t, 'l10n_it_pension_fund_type', False))
>    )
>    ```
>
> 3. **Whitelist esplicita dei tax_group_id validi per IVA** recuperati da configurazione.
>
> Prima di implementare, **analizzare il comportamento esatto del modulo `l10n_it_withholding` o equivalente** sul database target. Lanciare:
>
> ```sql
> SELECT column_name FROM information_schema.columns
> WHERE table_name='account_tax' AND column_name LIKE '%pension%' OR column_name LIKE '%welfare%' OR column_name LIKE '%cassa%';
> ```
>
> E controllare `tax_group_id` delle imposte Cassa vs imposte IVA.
>
> **Testare anche:** Ritenute d'acconto (che potrebbero essere configurate con amount negativo o tax_group specifico).

---

## Contesto architetturale

### Problema risolto dal modulo

Il modulo OCA `l10n_it_edi_extension` (v18.0.1.2.4, di Giuseppe Borruso — Dinamiche Aziendali) aggiunge il tab "Dettagli e-fattura" con campi popolati solo al parsing XML in ingresso, tramite il metodo `_l10n_it_edi_get_extra_info`. Non esiste logica di riallineamento alle modifiche successive della fattura, quindi:

- **Fatture attive create da zero:** tab sempre vuoto (zeri, tabelle vuote)
- **Fatture attive importate da XML + modificate:** tab congelato ai valori dell'import originale
- **Fatture passive importate da XML:** tab popolato correttamente al momento dell'import

### Scoperta diagnostica fondamentale

Il tab "Dettagli e-fattura" è **puramente informativo** per le fatture attive in Odoo 18 CE. Il core `l10n_it_edi` genera l'XML FatturaPA leggendo direttamente `account.move.line`, non i campi del tab. Le uniche eccezioni identificate tramite ispezione del template `/mnt/addons-italia/l10n_it_edi_extension/data/invoice_it_template.xml`:

1. `l10n_edi_it_art73` → usato nel template per generare `<Art73>SI</Art73>`
2. `company.l10n_edi_it_stable_organization` (non sulla fattura) → genera `<StabileOrganizzazione>`

**Tutti gli altri campi** (`l10n_it_edi_amount_*`, `l10n_it_edi_line_ids`, `l10n_it_edi_summary_ids`, `l10n_it_edi_stabile_organizzazione_*` sulla fattura, `l10n_it_edi_rounding`, `l10n_it_edi_activity_progress_ids`) **non sono letti dal template XML attivo**.

Questa scoperta permette al modulo di:
- Ricalcolare liberamente quei campi senza rischi fiscali
- Non alterare l'XML trasmesso
- Focalizzarsi sulla coerenza UI

## Struttura del modulo

```
odoomanager_edi_sync/
├── __init__.py                          # Imports models
├── __manifest__.py                      # Manifest (depends: l10n_it_edi_extension)
├── README.md                            # Doc installazione
├── models/
│   ├── __init__.py                      # Imports 3 moduli
│   ├── account_move.py                  # Meccanismi sync + metodo core
│   ├── l10n_it_edi_line.py              # Override create/write/unlink per lock
│   └── l10n_it_edi_summary_data.py      # Override create/write/unlink per lock
└── views/
    ├── account_move_sync_button.xml     # Pulsante manuale in header
    └── lock_edi_tables.xml              # Lock UI tabelle su fatture cliente
```

## Architettura del sync

### 3 meccanismi di trigger

Il modulo ha **3 punti di ingresso** che chiamano il metodo core `_om_sync_edi_details_silent()`:

1. **Override `create()` e `write()` su `account.move`** (meccanismo 1 — v3.0)
   - Trigger al salvataggio della fattura (include create e modifiche a `invoice_line_ids`)
   - Scelto al posto di `@api.onchange` per evitare errore Odoo 18 `'int' object has no attribute 'origin'` che si verificava quando onchange tentava di creare sub-record con `self.env[...].create()` (NewId vs Id reali)

2. **Override `_post()` su `account.move`** (meccanismo 2)
   - Safety net alla conferma fattura
   - Garantisce coerenza archivio anche se il trigger 1 è stato bypassato

3. **Action `action_om_sync_edi_details()`** (meccanismo 3)
   - Pulsante manuale in header form fattura
   - Disponibile solo su fatture cliente italiane in bozza
   - Mostra notifica display_notification al termine

### Context flag anti-ricorsione e bypass lock

Tutti i 3 meccanismi chiamano il metodo core **con `self.with_context(om_edi_sync_in_progress=True)`**. Questo flag serve a due scopi:

1. **Anti-ricorsione:** se il sync triggerasse a cascata altri write() o create() (es. su `invoice_line_ids`), il controllo `if self.env.context.get("om_edi_sync_in_progress"): return` nelle override previene loop infiniti.

2. **Bypass del lock tabelle:** gli override di `create()`/`write()`/`unlink()` su `l10n_it_edi.line` e `l10n_it_edi.summary_data` controllano questo flag e lasciano passare le operazioni interne al modulo. Le operazioni esterne (utente via UI, API, script) vengono bloccate con `UserError`.

### Metodo core `_om_sync_edi_details_silent()`

Esegue 3 step in ordine:

1. `_om_recompute_edi_amounts()` — aggiorna `l10n_it_edi_amount_untaxed` e `l10n_it_edi_amount_tax`
2. `_om_rebuild_edi_lines()` — `unlink()` + `create()` dei record `l10n_it_edi.line`
3. `_om_rebuild_edi_summary()` — `unlink()` + `create()` dei record `l10n_it_edi.summary_data` con aggregazione per (tax_rate, non_taxable_nature)

## Filtri applicati

### Righe fattura considerate

```python
def _om_get_product_lines(self):
    return self.invoice_line_ids.filtered(
        lambda line: line.display_type == "product"
    )
```

Esclude: `display_type` diverso da `product` (cioè sections, notes, payment_term, **tax** — quest'ultimo è la riga contabile speculare delle imposte).

### Imposte considerate IVA

```python
def _om_filter_iva_taxes(self, taxes):
    return taxes.filtered(
        lambda t: t.l10n_it_exempt_reason
        or (t.amount > 0 and t.amount_type == "percent")
    )
```

**⚠️ BUG NOTO:** vedi WARNING iniziale. Questo filtro include erroneamente la Cassa Previdenziale.

Esclude: imposte senza natura e con amount=0 o non percent (casi rari, es. ritenute con amount negativo, imposte accessorie contabili).

Include correttamente:
- Imposte con `l10n_it_exempt_reason` valorizzato (es. N2.2, N3.1, N4, N6.*)
- Imposte IVA ordinarie (22%, 10%, 4%, 5%)

**Include erroneamente:**
- Cassa Previdenziale (4%)
- Altre imposte % > 0 senza natura

### Ambito applicazione

Tutti i 3 meccanismi automatici sono limitati a:
```python
move.move_type in ("out_invoice", "out_refund")
and move.state == "draft"
and move.country_code == "IT"
```

Fatture passive (`in_invoice`, `in_refund`) sono **completamente escluse** per preservare dati XML ricevuti.
Fatture confermate (`posted`) sono escluse dai trigger write/create ma **NON dal _post()** (che è l'atto della conferma stessa).
Fatture annullate (`cancel`) sono escluse.

## Lock delle tabelle

### Override Python

I file `models/l10n_it_edi_line.py` e `models/l10n_it_edi_summary_data.py` contengono override di `@api.model_create_multi` (per `create`), `write`, `unlink`. La logica:

```python
def _om_check_customer_invoice_operation(self, records_or_vals, operation):
    if self.env.context.get("om_edi_sync_in_progress"):
        return  # Bypass per sync interno
    if self.env.su:
        return  # Bypass per superuser (migrazioni, -i, -u)

    # Identifica invoice_id dei record coinvolti
    # Se almeno uno è out_invoice/out_refund -> UserError
```

### Lock UI (vista)

`views/lock_edi_tables.xml` applica `readonly` condizionale ai due campi one2many:

```xml
<xpath expr="//field[@name='l10n_it_edi_line_ids']" position="attributes">
    <attribute name="readonly">move_type in ('out_invoice', 'out_refund')</attribute>
</xpath>
```

Questo nasconde "Aggiungi riga" e cestini sulle fatture cliente. Sulle fatture passive le tabelle restano editabili.

### Errori XML Odoo 18 — Note importanti

Durante lo sviluppo sono emersi questi errori Odoo 18 da evitare:

1. **`<attribute name="readonly" invisible="0">` non valido:** Odoo 18 non accetta attributi aggiuntivi dentro `<attribute>`. Usare solo `<attribute name="readonly">expr</attribute>`.

2. **`@api.onchange` + `.create()` su sub-record:** causa `AttributeError: 'int' object has no attribute 'origin'`. Odoo 18 usa NewId object durante onchange, i `.create()` si confondono tra NewId e Id reali. **Non usare questo pattern.** Preferire override di `write()`/`create()`.

3. **`db_password = False` nel odoo.conf:** Odoo 18 interpreta `False` come stringa letterale, causando `psycopg2.OperationalError: no password supplied` anche con PostgreSQL in trust mode. Workaround: passare `--db_password=""` da CLI.

## Informazioni ambiente di sviluppo originale

### Infrastruttura server Luigi

- **Server:** Aruba Cloud VPS (188.213.173.107, accesso SSH porta 59362 con chiave ED25519)
- **Host OS:** Ubuntu (container `odoo18-app`)
- **Stack:** Docker Compose con Odoo 18 CE + PostgreSQL (container id `3921ae9bea7d` al momento della doc)
- **Path host bind-mountati read-only nel container:**
  - `/home/odoo/odoo-docker/addons-italia/` → `/mnt/addons-italia/`
  - `/home/odoo/odoo-docker/custom-addons/` → `/mnt/custom-addons/`
  - `/home/odoo/odoo-docker/odoo-source/` → `/mnt/odoo-source/`
- **Database:** `odoo18`, utente `odoo`
- **odoo.conf:** `db_password = False` con PostgreSQL in trust mode — configurazione problematica ma funzionante

### Moduli rilevanti installati

- `l10n_it_edi` (core Odoo)
- `l10n_it_edi_extension` (OCA, v18.0.1.2.4, autore Giuseppe Borruso)
- `l10n_it_account_stamp` (OCA, gestione bollo forfettario)
- `l10n_it_edi_withholding` (OCA, gestione ritenute — verificare presenza prima di assumere)
- `l10n_it_pec` (custom di Luigi, trasmissione FatturaPA via PEC)

### Test fixtures di riferimento

**Fattura 156 (FATT/2026/00002)** — caso di test disallineamento:
- 2 righe prodotto: "Redazione 730" (60€) + "Sedia" (33€), totale 93€
- Imposte per riga: "0% Forfettario" (N2.2, tax_id=327) + "Cassa Previdenza Dottori Commercialisti" (4%, tax_id=325)
- amount_total = 96,72€ (93 + 3,72 di cassa)
- Prima del modulo, tab mostrava dati stantii dall'import XML originale (60€ "Redazione 730")

**Fattura 114 (ACQ/2026/04/0001)** — fattura passiva:
- Importo 5€ + IVA 22% = 6,10€
- Summary data popolato dall'import XML

### Discriminazione imposte IVA vs Cassa

Nel database di Luigi (da usare come riferimento per future query diagnostiche):

```sql
SELECT id, name::text, amount, amount_type,
       l10n_it_law_reference,
       l10n_it_exempt_reason,
       tax_group_id
FROM account_tax
WHERE id IN (325, 327);
```

| id | name | amount | amount_type | l10n_it_law_reference | l10n_it_exempt_reason | tax_group_id |
|----|------|--------|-------------|-----------------------|----------------------|--------------|
| 325 | Cassa Previdenza Dottori Commercialisti | 4.00 | percent | vuoto | vuoto | 43 |
| 327 | 0% Forfettario | 0.00 | percent | "Operazione senza applicazione..." | N2.2 | 44 |

**Discriminante corretto per v18.0.4.0.0:** utilizzare `tax_group_id` per distinguere Cassa dall'IVA, oppure il campo `l10n_it_pension_fund_type` se presente dal modulo `l10n_it_edi_withholding`.

## Storia evolutiva del modulo

### v18.0.1.0.0 — Solo pulsante manuale
- Azione manuale tramite pulsante in header
- Safety checks basic (draft, out_invoice, IT)

### v18.0.2.0.0 — Sync automatico
- Aggiunto `@api.onchange('invoice_line_ids')` per trigger reattivo
- Aggiunto override `_post()` come safety net alla conferma
- **BUG:** onchange + `.create()` su sub-record causava crash

### v18.0.3.0.0 — Lock tabelle + fix onchange
- `@api.onchange` sostituito da override di `create()` e `write()` per evitare NewId bug
- Aggiunto lock Python su `l10n_it_edi.line` e `l10n_it_edi.summary_data`
- Aggiunto lock UI in `lock_edi_tables.xml`
- **BUG NOTO:** Cassa Previdenziale inclusa nel filtro IVA

### v18.0.4.0.0 (FUTURE) — Fix Cassa Previdenziale
- Separare Cassa/Ritenute dal filtro IVA nel summary
- Verificare eventuale `tax_group_id` o flag specifici del modulo withholding OCA
- Test su fatture di professionisti (consulenti, avvocati, commercialisti, etc.)

## Roadmap funzionalità future da valutare

### 1. Fix Cassa Previdenziale (PRIORITARIO)
Vedi warning iniziale. Implementazione entro v18.0.4.0.0.

### 2. Gestione periodi competenza
Popolare `period_start_date` / `period_end_date` in `l10n_it_edi.line` da campi custom su `account.move.line` (richiede estensione del modello).

Utile per fatture ricorrenti (canoni mensili, consulenze periodiche).

### 3. Gestione SAL automatica
Popolare `l10n_it_edi_activity_progress_ids` da campi custom per le fatture di SAL (Stato Avanzamento Lavori).

### 4. Contributo a OCA
Valutare se il modulo può diventare un PR alla repository `OCA/l10n-italy` come miglioramento di `l10n_it_edi_extension`.

Requisiti OCA:
- Tests unitari completi
- README.rst in formato standard OCA
- Licenza compatibile (AGPL-3 per OCA)
- Coerenza con le convenzioni di codifica OCA

### 5. Automatismo click tab
Implementare refresh al click sul tab "Dettagli e-fattura" via JavaScript OWL custom. Complessità alta, valore marginale visto che ora il sync è già automatico al salvataggio.

## Comandi utili per sviluppo futuro

### Installazione da zero (ambiente Luigi)

```bash
# 1. Copia modulo via scp (dal PowerShell Windows)
scp -P 59362 -r -i "C:\Users\Utente\Documents\CHIAVE SSH\id_ed25519" \
    odoomanager_edi_sync root@188.213.173.107:/home/odoo/odoo-docker/addons-italia/

# 2. Sistema permessi (sul server)
cd /home/odoo/odoo-docker/addons-italia/
find odoomanager_edi_sync -type d -exec chmod 775 {} \;
find odoomanager_edi_sync -type f -exec chmod 664 {} \;

# 3. Installazione via CLI (workaround db_password=False)
docker exec odoo18-app odoo -d odoo18 -i odoomanager_edi_sync \
    --stop-after-init --no-http --db_password=""

# 4. Restart
docker restart odoo18-app
```

### Upgrade del modulo

```bash
docker exec odoo18-app odoo -d odoo18 -u odoomanager_edi_sync \
    --stop-after-init --no-http --db_password=""
docker restart odoo18-app
```

Se l'upgrade CLI non funziona, fallback dall'interfaccia web:
1. Modalità sviluppatore → App → Aggiorna elenco app
2. Cerca odoomanager → clicca card → pulsante "Aggiorna"

### Diagnostica stato modulo nel DB

```sql
SELECT name, latest_version, state
FROM ir_module_module
WHERE name = 'odoomanager_edi_sync';
```

### Verifica disallineamento tab vs realtà (diagnostica)

```sql
SELECT am.id, am.name, am.state, am.move_type,
       am.amount_untaxed AS totale_reale,
       am.amount_total AS totale_con_imposte,
       am.l10n_it_edi_amount_untaxed AS tab_imponibile,
       am.l10n_it_edi_amount_tax AS tab_imposta
FROM account_move am
WHERE am.move_type IN ('out_invoice', 'out_refund')
  AND am.country_code = 'IT'
  AND (
    am.l10n_it_edi_amount_untaxed != am.amount_untaxed
    OR am.l10n_it_edi_amount_untaxed IS NULL
  );
```

Ritorna le fatture cliente con tab disallineato dai dati reali.

### Ricontrollo imposte IVA vs non-IVA

Per analizzare come distinguere Cassa/Ritenute dall'IVA nel tuo database:

```sql
SELECT at.id, at.name::text, at.amount, at.amount_type,
       at.l10n_it_exempt_reason,
       at.l10n_it_law_reference,
       atg.name::text AS gruppo_imposta
FROM account_tax at
LEFT JOIN account_tax_group atg ON atg.id = at.tax_group_id
WHERE at.type_tax_use = 'sale'
ORDER BY atg.id, at.amount;
```

## Note conclusive

Il modulo nasce per risolvere uno specifico problema dell'ecosistema OCA italiano in Odoo 18. È stato sviluppato iterativamente tramite dialogo con Claude (modello Opus 4.7), con diagnosi progressiva del codice OCA via grep/cat sui file del container Docker, verifiche SQL dirette sul database, e test funzionali sulla fattura 156 di riferimento.

**Il modulo ha un bug noto critico per professionisti con Cassa Previdenziale** (vedi warning iniziale) che deve essere risolto in una futura versione prima di distribuzione massiva a clienti OdooManager.cloud appartenenti a categorie professionali (commercialisti, avvocati, ingegneri, architetti, consulenti del lavoro, geometri, notai, medici).

Per l'utilizzo con forfettari senza Cassa (es. piccoli artigiani, commercianti, consulenti in regime forfettario puro senza cassa), il modulo v18.0.3.0.0 è **pienamente funzionale**.
