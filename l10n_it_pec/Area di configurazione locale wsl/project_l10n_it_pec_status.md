---
name: l10n_it_pec - Stato sviluppo modulo
description: Resoconto completo dello stato di sviluppo del modulo Odoo 18 per invio fatture elettroniche via PEC allo SDI, architettura, decisioni, problemi noti e TODO
type: project
---

# l10n_it_pec — Stato sviluppo (aggiornato 2026-03-30)

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
│   └── pec_mail_handler.py            # AbstractModel: polling IMAP, parsing notifiche SDI
├── views/
│   ├── account_move_views.xml         # Bottoni PEC su fattura, campi informativi, azione wizard
│   ├── res_company_views.xml          # Tab PEC nella form company
│   └── res_config_settings_views.xml  # Sezione PEC in settings + hide blocchi SDI standard
├── wizard/
│   ├── __init__.py
│   ├── pec_send_wizard.py             # Wizard invio massivo da lista fatture
│   └── pec_send_wizard_views.xml      # Vista wizard
├── security/
│   ├── res_groups.xml                 # Gruppo: group_pec_manager
│   └── ir.model.access.csv           # ACL: wizard + mail handler
├── data/
│   └── cron_data.xml                  # Cron polling IMAP ogni 15 minuti
└── tests/
    ├── __init__.py
    └── test_pec.py                    # Test configurazione e notifiche SDI
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

## Problemi noti e possibili TODO

### Corretti (sessione 2026-03-30)
1. ~~**`account_move_send.py` vuoto**~~ — File eliminato e rimosso da `__init__.py`. Se Odoo CE rendera `account.move.send` un TransientModel, si potra creare un nuovo file.
2. ~~**Wizard `pec_send_wizard.py` — riferimento a `'disabled'`**~~ — Rimosso check `pec_mode == 'disabled'` dal Python e `invisible` dalla vista XML.
3. ~~**Test `test_pec.py` — riferimenti a `'disabled'`**~~ — Setup cambiato a `'demo'`, test_01 e test_11 adattati (test_11 ora testa `pec_mode = False`).
4. ~~**Fatture passive — `_l10n_it_edi_import_invoices()`**~~ — Aggiunto guard `hasattr` con warning log se il metodo non esiste nella versione Odoo installata.
5. ~~**Wizard invio massivo — chiamata senza argomenti**~~ — `_l10n_it_pec_send_to_sdi()` sostituito con `action_l10n_it_pec_send()` che gestisce il flusso completo.
6. ~~**Messaggi in inglese**~~ — Tradotti in italiano i 2 messaggi nel chatter (demo + notifica SDI) in `account_move.py`.

### Da fare (prossimi passi)
- **Test funzionale end-to-end** in modalita demo: creare fattura, confermare, inviare via PEC, verificare chatter e wizard massivo.
- **Test con Odoo 18 CE reale** per verificare compatibilita `_l10n_it_edi_import_invoices()` e flusso `_l10n_it_edi_send()`/`_l10n_it_edi_upload()`.
- **Test firma digitale PA**: verificare flusso download XML, upload .p7m firmato, invio PEC con file firmato.

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
