---
name: l10n_it_pec - Stato sviluppo modulo
description: Resoconto completo dello stato di sviluppo del modulo Odoo 18 per invio fatture elettroniche via PEC allo SDI, architettura, decisioni, problemi noti e TODO
type: project
---

# l10n_it_pec — Stato sviluppo (aggiornato 2026-04-12, terza sessione del giorno)

## Obiettivo del modulo
Modulo Odoo 18 CE che sostituisce il trasporto delle fatture elettroniche italiane (FatturaPA) verso lo SDI: **PEC invece del proxy IAP Odoo**. Il modulo cambia SOLO il layer di trasporto, delegando TUTTA la gestione degli stati EDI allo standard Odoo (`l10n_it_edi`).

**Why:** L'utente (OdooManager.cloud) vuole offrire un'alternativa all'invio SDI via proxy Odoo, usando PEC certificata come canale ufficiale accreditato dall'Agenzia delle Entrate.

## Architettura — "Opzione C" (ibrida)

### Principio fondamentale
> PEC è un backend di trasporto alternativo, NON un sistema parallelo. L'XML è generato dallo standard, gli stati sono gestiti dallo standard, solo il "come spedisco" cambia.

### Punto di intercettazione
- **`_l10n_it_edi_upload(files)`** — override del metodo di trasporto. Ritorna `{filename: {'id_transaction': message_id}}` o `{filename: {'error': ..., 'error_description': ...}}`. Il chiamante `_l10n_it_edi_send()` gestisce autonomamente stato, transaction, header e messaggi chatter.
- **`_l10n_it_edi_send(attachments_vals)`** — override SOLO per la modalità demo (dry-run senza cambio stato EDI). PEC test/production passano al `super()` che chiama `_l10n_it_edi_upload`.
- **`_l10n_it_edi_update_send_state()`** — override per separare fatture PEC (polling IMAP) da fatture proxy (flusso standard) nel cron.
- **`action_check_l10n_it_edi()`** — override per il bottone "Controlla invio": discrimina sulla transaction della fattura (non sulla config company).

### Identificazione transaction PEC
Le transaction PEC si riconoscono dal prefisso:
- `<` → Message-ID SMTP reale (es. `<abc123@pec.aruba.it>`)
- `pec_` → fallback se Message-ID non disponibile

NON include `demo` perche anche il proxy standard usa `'demo'` come transaction ID.

### Flusso standard Odoo 18 EDI
```
account.move.send → _l10n_it_edi_send() → _l10n_it_edi_upload() → proxy IAP
                         ↓ gestisce:                ↓ ritorna:
                    stato, transaction,         {id_transaction} o {error}
                    header, chatter
```

### Flusso PEC (test/production)
```
account.move.send → _l10n_it_edi_send() [standard] → _l10n_it_edi_upload() [PEC override] → SMTP PEC
```

### Flusso PEC (demo)
```
account.move.send → _l10n_it_edi_send() [PEC override] → simulazione, nessun cambio stato
```

### Flusso ricezione fatture passive (verificato end-to-end 2026-04-10)
```
cron ogni 15 min → _cron_poll_pec_inbox()
   → IMAP UNSEEN FROM @pec.fatturapa.it
   → dispatch per ogni allegato XML/p7m:
       - _metadati.xml o _MT_NNN.xml → skip esplicito
       - notifica SDI (RC/NS/MC/AT/NE/DT) → _handle_sdi_notification()
       - fattura passiva (regex PASSIVE) → _handle_passive_invoice()
           ├─ dedup su filename → skip se già importata
           ├─ account.move vuota + ir.attachment con res_field='l10n_it_edi_attachment_file'
           ├─ invalidate_recordset(['l10n_it_edi_attachment_id', 'l10n_it_edi_attachment_file'])
           ├─ message_post(attachment_ids=move.l10n_it_edi_attachment_id.ids)
           ├─ _extend_with_attachments(edi_attachment, new=True) ← KEY: innesca decoder FatturaPA
           ├─ se partner_id popolato → successo, allega .eml del PEC originale
           └─ se partner_id vuoto o eccezione → quarantena (attachment orfano QUARANTINE_*)
```

## Modalita operative
| Modalita | Comportamento | Stato EDI |
|-----------|--------------|-----------|
| `demo` | Genera XML, simula invio, logga nel chatter | **Nessun cambio** (no processing, no transaction) |
| `test` | Invio reale PEC all'indirizzo di test SDI | Gestito dallo standard (processing → forwarded/rejected) |
| `production` | Invio reale PEC all'indirizzo SDI ufficiale | Gestito dallo standard |

- Non esiste piu l'opzione `disabled` — PEC e sempre attiva con il modulo installato (default: `demo`).
- Il modulo nasconde automaticamente le opzioni di configurazione proxy SDI standard nelle Impostazioni.

## Struttura file del modulo

```
l10n_it_pec/
├── __manifest__.py                    # v18.0.1.0.0, depends: account, l10n_it_edi, mail
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── account_move.py                # CUORE: override trasporto EDI, notifiche SDI
│   ├── res_company.py                 # Campi config PEC, test connessione SMTP/IMAP
│   ├── res_config_settings.py         # Campi related per settings
│   └── pec_mail_handler.py            # AbstractModel: polling IMAP, parsing notifiche SDI, import passive
├── views/
│   ├── account_move_views.xml         # Bottoni PEC su fattura, campi informativi, azione wizard
│   ├── res_company_views.xml          # Tab PEC nella form company
│   └── res_config_settings_views.xml  # Sezione PEC in settings + hide blocchi SDI standard
├── wizard/
│   ├── __init__.py
│   ├── pec_send_wizard.py             # Wizard invio massivo da lista fatture
│   ├── pec_send_wizard_views.xml      # Vista wizard
│   ├── pec_upload_signed_wizard.py    # Wizard upload XML firmato per fatture PA
│   └── pec_upload_signed_wizard_views.xml
├── security/
│   ├── res_groups.xml                 # Gruppo: group_pec_manager
│   └── ir.model.access.csv           # ACL: wizard + mail handler
├── data/
│   └── cron_data.xml                  # Cron polling IMAP ogni 15 minuti
└── tests/
    ├── __init__.py                    # Importa test_pec (corretto 2026-04-10, prima era vuoto)
    └── test_pec.py                    # Test configurazione, notifiche SDI, fatture passive
```

## Gestione switch PEC ↔ SDI standard

Scenario critico: l'utente invia fatture via PEC, poi disattiva PEC e passa al proxy standard.

**Soluzione implementata:**
1. `action_check_l10n_it_edi()` — discrimina sulla **transaction della fattura** (non sulla config company corrente). Una fattura con transaction PEC viene sempre controllata via IMAP.
2. `_l10n_it_edi_update_send_state()` — nel cron standard, separa le fatture PEC da quelle proxy. Le PEC vanno a IMAP polling, le proxy al flusso nativo.
3. `_cron_poll_pec_inbox()` — cerca anche company con fatture PEC pendenti anche se la company non ha piu PEC attiva.

## Gestione visibilita settings standard SDI

Il modulo nasconde i blocchi `account_edi` e `account_edi_branch` (configurazione proxy SDI di `l10n_it_edi`) nelle Impostazioni tramite una view ereditata. Alla disinstallazione del modulo PEC, la view viene rimossa automaticamente e i blocchi standard riappaiono.

## Notifiche SDI supportate
| Codice | Significato | Stato EDI risultante |
|--------|-------------|---------------------|
| RC | Ricevuta di Consegna | `forwarded` |
| NS | Notifica di Scarto | `rejected` |
| MC | Mancata Consegna | `forward_attempt` |
| AT | Attestazione trasmissione | `forwarded` |
| NE (EC01) | Notifica Esito - Accettazione | `forwarded` |
| NE (EC02) | Notifica Esito - Rifiuto | `rejected` |
| DT | Decorrenza Termini (silenzio-assenso) | `forwarded` |

Le notifiche vengono processate con `_l10n_it_edi_write_send_state()` (metodo standard Odoo) per coerenza atomica di stato/transaction/header.

## Acquisizione fatture passive — Stato: COMPLETATO E VERIFICATO END-TO-END (2026-04-10)

### Pattern di import (verificato su istanza reale Odoo 18 CE)
Il metodo `_l10n_it_edi_import_invoices` (plurale) che cercavamo inizialmente **non esiste** in Odoo 18 CE. Esiste invece `_l10n_it_edi_create_move_with_attachment` (nel flusso proxy IAP, non usabile direttamente perché richiede `proxy_user` e contenuto cifrato) e il pattern di innesco del decoder FatturaPA che abbiamo replicato.

Il pattern corretto, replicato riga per riga dal codice standard Odoo (`l10n_it_edi/models/account_move.py` righe 239-240 e 972):

```python
move = env['account.move'].with_company(company).create({'move_type': 'in_invoice'})
env['ir.attachment'].sudo().with_company(company).create({
    'name': filename,
    'raw': xml_bytes,
    'type': 'binary',
    'res_model': 'account.move',
    'res_id': move.id,
    'res_field': 'l10n_it_edi_attachment_file',  # ← campo speciale
})
move.invalidate_recordset(fnames=['l10n_it_edi_attachment_id', 'l10n_it_edi_attachment_file'])
edi_attachment = move.l10n_it_edi_attachment_id  # ← computed, ora punta all'attachment
move.with_context(
    account_predictive_bills_disable_prediction=True,
    no_new_invoice=True,
).message_post(attachment_ids=edi_attachment.ids)
move._extend_with_attachments(edi_attachment, new=True)  # ← innesca decoder FatturaPA
```

**Attenzione**: `message_post` da solo NON basta da codice — innesca il decoder solo quando fatto dall'UI (drag & drop). Da codice serve chiamare esplicitamente `_extend_with_attachments` come secondo passaggio. Questo è stato il fix chiave della sessione 2026-04-10.

### Garanzie implementate in `_handle_passive_invoice`
- **Deduplica**: check `ir.attachment` con lo stesso nome collegato a una `account.move` della stessa company. Se trovato → skip.
- **Quarantena**: se `message_post`/`_extend_with_attachments` sollevano eccezione, OR se dopo il giro `partner_id` resta vuoto (decoder non agganciato), l'XML viene salvato come `ir.attachment` orfano con nome `QUARANTINE_<filename>` e descrizione con il motivo. La move vuota viene cancellata per non sporcare il DB.
- **Archivio `.eml`**: quando l'import ha successo e `raw_email` è disponibile, il messaggio PEC originale viene allegato alla fattura importata come `message/rfc822` per conservazione/audit.

### Pattern filename supportati (regex)
- **Fattura passiva**: `^[A-Z]{2}[A-Z0-9]{2,28}_[A-Z0-9]+\.xml(\.p7m)?$` — accetta XML puro e CAdES, case insensitive, codici paese non solo IT, progressivo alfanumerico.
- **Metadati SDI (skip esplicito)**: `(_metadati|_MT_\d+)\.xml$` — matcha sia `_metadati.xml` canonico, sia `_MT_NNN.xml` usato da Aruba.

### Test end-to-end riuscito (2026-04-10)
Importata fattura Aruba reale `IT01879020517A2026_cwbJU.xml.p7m` (6,10 € servizio casella PEC) via cron automatico:
- File metadati `_MT_001.xml` → ignorato correttamente
- File fattura `.xml.p7m` → riconosciuto, importato, `partner_id` popolato da Aruba SPA
- `daticert.xml` (certificato firma PEC) → saltato come "non riconosciuto" (comportamento corretto)
- Nessuna quarantena, fattura creata in bozza

## Problemi noti e possibili TODO

### Corretti (sessione 2026-03-30)
1. ~~**`account_move_send.py` vuoto**~~ — File eliminato e rimosso da `__init__.py`.
2. ~~**Wizard `pec_send_wizard.py` — riferimento a `'disabled'`**~~ — Rimosso.
3. ~~**Test `test_pec.py` — riferimenti a `'disabled'`**~~ — Setup cambiato a `'demo'`.
4. ~~**Wizard invio massivo — chiamata senza argomenti**~~ — `_l10n_it_pec_send_to_sdi()` sostituito con `action_l10n_it_pec_send()`.
5. ~~**Messaggi in inglese**~~ — Tradotti in italiano i 2 messaggi nel chatter.

### Corretti (sessione 2026-04-10) — Acquisizione fatture passive end-to-end
1. ~~**Fatture passive — `_l10n_it_edi_import_invoices()` non esisteva**~~ — Il metodo cercato era al plurale e non esiste in Odoo 18 CE. Sostituito con il pattern ufficiale `message_post` + `_extend_with_attachments` esplicito letto dal codice standard Odoo.
2. ~~**Regex `SDI_PASSIVE_INVOICE_PATTERN` troppo restrittivo**~~ — Era `IT\d{11}_\w+\.xml` (solo IT, solo XML puro, solo 11 cifre). Esteso a `^[A-Z]{2}[A-Z0-9]{2,28}_[A-Z0-9]+\.xml(\.p7m)?$` per accettare CAdES firmate, fornitori esteri, progressivi alfanumerici.
3. ~~**File metadati SDI non gestito esplicitamente**~~ — Prima veniva loggato come "XML non riconosciuto". Aggiunto `SDI_METADATA_FILENAME_PATTERN` che matcha sia `_metadati.xml` sia `_MT_NNN.xml` (formato Aruba) con skip esplicito nel dispatcher.
4. ~~**Deduplica assente**~~ — Aggiunto check su `ir.attachment` con lo stesso nome collegato a una move della stessa company, prima dell'import. Protegge da doppio processing del cron.
5. ~~**Quarantena in caso di errore**~~ — Prima un fallimento del decoder avrebbe perso l'XML. Ora: tre rami di quarantena (metodo mancante, eccezione durante `message_post`, `partner_id` non popolato), tutti salvano il file come `ir.attachment` orfano `QUARANTINE_*`.
6. ~~**Archivio `.eml` del messaggio PEC originale**~~ — Quando l'import ha successo, il `.eml` viene allegato alla fattura importata per conservazione/audit GdF.
7. ~~**`tests/__init__.py` vuoto**~~ — Il file era letteralmente vuoto (solo commento encoding), quindi `test_pec.py` non veniva mai eseguito da Odoo. Corretto aggiungendo `from . import test_pec`. Questa è stata la scoperta che ha fatto emergere tutti i problemi successivi nei test.
8. ~~**`_logger.info` crashava su move senza name**~~ — `', '.join(created_moves.mapped('name'))` sollevava `TypeError` se una move importata non aveva ancora `name` (bozza non numerata). Fix difensivo con fallback `(draft #{m.id})`.

### Debito tecnico risolto (sessione 2026-04-10 — seconda parte)
- ~~**5 test storici rotti (test_13 → test_17)**~~ — Testavano le notifiche SDI (RC, NS, NE accepted, NE rejected, DT) e fallivano tutti con `AssertionError: Cannot commit or rollback a cursor from inside a test`. La causa era che chiamavano `invoice._l10n_it_pec_process_sdi_notification(...)` che internamente chiama `_l10n_it_edi_write_send_state()` (metodo standard Odoo), il quale fa `self.env.cr.commit()`. Il commit è vietato nei test Odoo perché rompe la transazione di rollback.
  - **Fix applicato**: aggiunto `setUp()` a livello di istanza nella classe `TestPecAccountMove` che installa un `patch.object` su `_l10n_it_edi_write_send_state`. Il patch lo sostituisce con una funzione `_fake_write_send_state` che scrive direttamente i campi `l10n_it_edi_state` e `l10n_it_edi_transaction` dalla `transformed_notification` passata, senza committare e senza postare sul chatter. Il patch vive per la durata del singolo test e viene rimosso automaticamente da `addCleanup(patcher.stop)` al termine.
  - **Why questa strategia e non altre**: (1) non tocca il codice di produzione (`account_move.py` resta intatto, principio minimal change); (2) il fix è in un singolo punto (setUp della classe) e vale per tutti e 5 i test; (3) è idiomatico rispetto a `unittest.mock`; (4) non aggiunge branch "if test_mode" al codice di produzione, che sarebbe una contaminazione brutta.
  - **File modificato**: `tests/test_pec.py` (solo, niente altro).
  - **Risultato verificato**: suite di test completamente verde per la prima volta — `l10n_it_pec: 33 tests, 0 failed, 0 error(s) of 27 tests`.

### Corretti (sessione 2026-04-10 — terza parte, rifiniture)
1. ~~**Warning ARIA sulle viste**~~ — Odoo 18 emetteva al caricamento del modulo due WARNING sulla vista `account_move_views.xml`: *"An alert (class alert-\*) must have an alert, alertdialog or status role or an alert-link class"*. I warning riguardavano i due `<div class="alert alert-warning mb-0">` e `<div class="alert alert-success mb-0">` del blocco firma digitale PA, che mancavano dell'attributo ARIA `role`. Fix: aggiunto `role="alert"` su entrambi i div. Zero impatto funzionale, solo conformità WAI-ARIA e log puliti.
  - **File modificato**: `views/account_move_views.xml` (solo, due attributi aggiunti).
2. ~~**Password PostgreSQL esposta in chat**~~ — Durante le sessioni di debug del 2026-04-09/2026-04-10 la password del DB è stata incollata nei messaggi in chat per via di alcuni comandi one-shot. Ruotata con `openssl rand -base64 24`, aggiornato `.env`, eseguito `ALTER USER odoo WITH PASSWORD '...'` su PostgreSQL, riavviati i container. La vecchia password non è più valida.

### Corretti (sessione 2026-04-12) — Persistenza IdentificativoSdI
Implementata la conservazione dell'`IdentificativoSdI` dal file metadati FatturaPA accluso al messaggio PEC, voce che era nel "Da fare" come "valutare se" e che è stata promossa a feature concreta su richiesta dell'utente.

**Why**: l'`IdentificativoSdI` è il numero univoco assegnato dal Sistema di Interscambio a ogni trasmissione di fattura. È fondamentale per audit, conservazione sostitutiva, e dispute con il fornitore ("la fattura X mi è arrivata via SDI con ID Y in data Z"). Senza di esso, in caso di contestazione, non c'è modo di provare con certezza che lo SDI ha effettivamente recapitato quella specifica fattura a quella specifica casella.

**Come funziona**:
1. Quando il cron PEC processa un messaggio dallo SDI, oltre ad estrarre la fattura `IT*.xml.p7m` ora **scansiona anche** il file metadati `IT*_MT_NNN.xml` accluso (che fino a ieri veniva semplicemente saltato).
2. Dal file metadati estrae il tag `<IdentificativoSdI>` con un regex permissivo che accetta namespace prefix opzionale, whitespace attorno al valore, case insensitive.
3. L'identifier viene passato come parametro extra a `_handle_passive_invoice` insieme a fattura, raw_email e subject.
4. Dopo che il parser FatturaPA standard ha popolato la fattura fornitore (e quindi solo se l'import è andato a buon fine), l'identifier viene scritto sul nuovo campo `l10n_it_pec_sdi_identifier` della move.
5. Il campo è visibile in sola lettura nella form della fattura fornitore, in un nuovo gruppo "Ricezione PEC SDI" del tab "Altre informazioni". Il gruppo è nascosto se l'identifier è vuoto (così non ingombra le fatture fornitore inserite a mano, che non passano dal cron).

**Robustezza**:
- Se il file metadati non c'è nel messaggio PEC, o è malformato, o non contiene il tag, l'identifier resta `None` e l'import della fattura procede normalmente. **Un identifier mancante non blocca mai l'import**.
- La scrittura del campo è in `try/except` con log warning: se per qualche ragione il `write` fallisce (es. eccezione concorrente), la fattura resta importata e usabile, semplicemente senza l'identifier.
- Quando un messaggio PEC contiene più fatture + più metadati (caso raro ma possibile), `_find_sdi_identifier_for_invoice` fa match per prefisso del filename per associare correttamente ogni fattura al suo metadati.

**File modificati** (4 in totale, niente refactoring):
- `models/account_move.py` — aggiunto il campo `l10n_it_pec_sdi_identifier` (Char, readonly, copy=False, indexed) in coda al blocco campi PEC esistenti
- `models/pec_mail_handler.py` — aggiunto regex `SDI_IDENTIFIER_PATTERN`, helper `_extract_sdi_identifier_from_metadata`, helper `_find_sdi_identifier_for_invoice`, modificato `_process_pec_message` per pre-estrarre l'identifier prima di chiamare l'handler, modificato `_handle_passive_invoice` per accettare e scrivere il nuovo parametro `sdi_identifier`
- `views/account_move_views.xml` — aggiunto un secondo gruppo `pec_info_in` (parallelo all'esistente `pec_info` che è solo per le attive) che mostra il campo solo per le fatture passive con identifier valorizzato
- `tests/test_pec.py` — aggiunti 3 nuovi test in coda a `TestPecPassiveInvoices`:
  - `test_35_extract_sdi_identifier_from_metadata`: 5 casi di estrazione (canonico SDI, namespace prefix, whitespace, tag mancante, malformato)
  - `test_36_find_sdi_identifier_with_multiple_metadata`: match per prefisso quando un messaggio PEC contiene più metadati
  - `test_37_passive_invoice_writes_sdi_identifier`: end-to-end con mock di `message_post` che simula import riuscito

**Risultato verificato**: suite di test passa da 27 a 30 test eseguiti, tutti verdi. `l10n_it_pec: 36 tests, 0 failed, 0 error(s) of 30 tests`. Migrazione del campo nel DB confermata da `module l10n_it_pec: creating or updating database tables` nei log di update.

**Verifica end-to-end sul cron reale (2026-04-12)**: la prima fattura passiva arrivata via PEC sulla casella `sdifatture@pec.it` dopo l'update del modulo è stata processata correttamente dal nuovo flusso. Il regex `SDI_IDENTIFIER_PATTERN` ha matchato il file metadati `_MT_NNN.xml` reale di Aruba al primo colpo, l'IdentificativoSdI è stato estratto, scritto sulla fattura importata, ed è visibile nel nuovo gruppo "Ricezione PEC SDI" del tab "Altre informazioni". **Non è stato necessario estendere il regex**: la prima implementazione era già corretta sui file metadati reali. Punto chiuso definitivamente.

### Corretti (sessione 2026-04-12 — pomeriggio) — Cleanup DB orfano `date_range_account`
Risolto il warning ricorrente che a ogni avvio di Odoo emetteva:
```
WARNING ... odoo.modules.graph: module date_range_account: not installable, skipped
ERROR   ... odoo.modules.loading: Some modules are not loaded, some dependencies or manifest may be missing: ['date_range_account']
```

**Diagnosi vera (dopo varie ipotesi sbagliate)**: la cartella `date_range_account` non esisteva sul filesystem né dell'host né dentro il container. Nessun manifest di nessun modulo lo dichiarava come dipendenza. Eppure il warning compariva a ogni avvio. La causa era un **record orfano nella tabella `ir_module_module` del database**: in qualche momento del passato il modulo era stato installato (probabilmente come parte di un repo OCA `account-financial-reporting` o simile), poi la cartella era stata rimossa dal filesystem (durante un upgrade del repo o una migrazione), ma il record nel DB era rimasto a stato `installed` con `latest_version = 18.0.1.0.0`. A ogni avvio Odoo costruiva il grafo dei moduli partendo da quel record fantasma, non trovava la cartella corrispondente, e bestemmiava.

**Fix applicato**: cancellazione del record orfano dal DB in transazione SQL singola (`BEGIN/COMMIT`), in 5 passi atomici:
1. `DELETE FROM ir_ui_menu` per le 4 voci di menu collegate
2. `DELETE FROM ir_model_access` per i 3 permessi ACL collegati
3. `DELETE FROM ir_model_data WHERE module = 'date_range_account'` per i 7 metadati associati
4. `UPDATE ir_module_module SET state = 'uninstalled'` come passaggio buffer per coerenza
5. `DELETE FROM ir_module_module WHERE name = 'date_range_account'` per il record principale

Tutto in un blocco `BEGIN; ... COMMIT;` con verifica finale `SELECT COUNT(*)` integrata, così se qualcosa fosse andato storto la transazione veniva rollbackata automaticamente. Backup precauzionale di `ir_module_module` e `ir_model_data` salvato in `/home/odoo/backup_pre_date_range_account_cleanup.sql` prima di toccare niente.

**Verifica preliminare (prima di toccare il DB)**: query `information_schema.columns` per cercare colonne residue su tabelle di account: trovate 9 colonne `*date_range*` ma TUTTE appartenenti al modulo `date_range` "padre" (che è installato e funzionante) o al core Odoo, NESSUNA del modulo `date_range_account`. Confermato che il cleanup non avrebbe lasciato colonne orfane su `account_move` o simili.

**Risultato verificato**: dopo restart del container e nuovo run completo dei test (`docker compose exec odoo odoo -d odoo18 -u l10n_it_pec --test-enable --stop-after-init ...`), nei log NON compare più né il `WARNING ... module date_range_account: not installable, skipped` né l'`ERROR ... Some modules are not loaded`. Suite test verde: `l10n_it_pec: 36 tests, 0 failed, 0 error(s) of 30 tests`.

**Note sulla diagnosi sbagliata iniziale**: la prima ipotesi era che `date_range_account` fosse un modulo "rotto" sul filesystem con dipendenze mancanti (causa A o B). Diversi `find` e `grep` ricorsivi hanno smontato questa ipotesi, ma fino al momento in cui non abbiamo controllato il DB direttamente non avevamo visto il record orfano. Lezione: quando Odoo si lamenta di un modulo "not installable", controllare SEMPRE prima `ir_module_module` nel DB, non solo il filesystem. Il messaggio di errore è leggermente fuorviante (parla di "dipendenze mancanti" anche quando in realtà è un record orfano).

### Da fare (prossimi passi)
- **Test firma digitale PA**: verificare flusso download XML, upload .p7m firmato, invio PEC con file firmato (non ancora testato end-to-end su istanza reale). Richiede una fattura vera verso un ente PA e un certificato di firma digitale qualificata. Rimandabile finché non emerge un cliente OdooManager.cloud che fattura a enti pubblici.
- **Warning cosmetico font Courier**: Odoo logga `Warn: Can't find .pfb for face 'Courier'` a ogni avvio (warning di `wkhtmltopdf`, non blocca generazione PDF). Identico in spirito al fix di `date_range_account`: residuo dell'immagine Docker, da sistemare solo per pulizia. Non urgente.
- **Considerazioni operative (da documentare nel runbook OdooManager.cloud, non nel codice):**
  - Il cron filtra i messaggi PEC con `UNSEEN FROM "@pec.fatturapa.it"`. Se un operatore apre la webmail PEC del cliente e clicca su un messaggio SDI, questo diventa `\Seen` e il cron **non lo importerà più** — la dedup comunque protegge da import duplicati se questo succede al contrario.
  - Il polling IMAP gira in sequenza su tutte le company con PEC attiva. Con molte company (50+) potrebbe diventare un collo di bottiglia — da monitorare se si scala.
  - Per i comandi di test/admin che toccano il DB, usare sempre `-e PGPASSWORD=$(grep POSTGRES_PASSWORD /home/odoo/odoo-docker/.env | cut -d= -f2)` con uno spazio iniziale, così la password non finisce mai in chiaro né nella history bash né nei log della chat. Aggiungere `-T` quando il comando dentro `exec` ha I/O redirezionato (heredoc, pipe, `>`, `<`).
  - Quando si lanciano comandi `docker compose`, **andare prima nella cartella `/home/odoo/odoo-docker/`** (dove sta il file `docker-compose.yml`), altrimenti `docker compose` non trova la configurazione e fallisce con `no configuration file provided: not found`.

### Feature: Firma digitale fatture PA (aggiunta 2026-04-01)
Flusso manuale download/upload per firma digitale qualificata delle fatture PA (obbligatoria per legge).
- Usa campo standard `l10n_it_partner_is_public_administration` di l10n_it_edi per discriminare PA
- 3 nuovi campi: `l10n_it_pec_signed_attachment_id`, `l10n_it_pec_signature_required` (computed), `l10n_it_pec_signature_state` (computed)
- Wizard `l10n_it_pec.upload.signed.wizard` per upload con validazione (formato, header ASN.1, corrispondenza filename)
- In `_l10n_it_edi_upload`: se PA con firma, sostituisce contenuto; se PA senza firma, blocca invio con errore
- Il filename originale resta come chiave nei risultati (il chiamante `_l10n_it_edi_send` lo usa per il lookup)
- `pec_mail_handler.py` gia gestisce `.p7m` in `_extract_invoice_reference` — nessuna modifica necessaria

### Decisioni architetturali consolidate
- **MAI gestire stati EDI in parallelo** — solo lo standard li gestisce
- **Override al livello piu basso possibile** — `_l10n_it_edi_upload` per il trasporto
- **Demo = zero side-effect** — nessun cambio stato, solo log e XML salvato
- **Transaction-based discrimination** — per switch PEC/proxy senza corruzione
- **Delega totale al parser FatturaPA standard** per l'import passive — NON scrivere un parser XML in proprio. Il modulo `l10n_it_pec` resta un layer di trasporto + dispatcher, non implementa logica di parsing fatture.
- **`_extend_with_attachments` esplicito** dopo `message_post` quando si importa da codice — il drop manuale via UI e l'invocazione da codice si comportano diversamente rispetto al decoder FatturaPA. Da codice serve chiamare entrambi i metodi in sequenza.
