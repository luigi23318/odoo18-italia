# l10n_it_pec — Fatturazione Elettronica via PEC per Odoo 18 CE

## Architettura Opzione C (Ibrida)

Questo modulo integra l'invio della fatturazione elettronica italiana (FatturaPA) allo SDI tramite PEC come **backend EDI alternativo** all'interno del flusso standard di Odoo 18.

### Principio fondamentale

**PEC NON è un sistema parallelo** — è un canale di trasporto alternativo dentro il pipeline EDI nativo di Odoo.

```
account.move
    ↓
_l10n_it_edi_send()          ← OVERRIDE: intercetta qui
    ├── SDI standard (proxy Odoo)   ← se PEC disabled
    └── PEC (SMTP)                  ← se PEC attiva
    ↓
l10n_it_edi_state             ← UNICO stato, nessuna duplicazione
    ↓
Notifiche SDI via IMAP        ← cron polling → aggiorna stato standard
```

### Cosa cambia rispetto al modulo originale

| Aspetto | Modulo originale | Opzione C (questo) |
|---|---|---|
| Architettura | Parallela (stati duplicati) | Integrata (stato EDI unico) |
| Override | `_post()` con invio automatico | `_l10n_it_edi_send()` — trasporto |
| Stati | `l10n_it_edi_pec_state` custom | `l10n_it_edi_state` standard |
| Wizard | Nessuno | Integrato in "Invia e Stampa" |
| Notifiche SDI | Non gestite | IMAP polling + mapping stati |
| Fatture passive | Non gestite | Import automatico da PEC |
| Modalità demo | Non presente | Dry-run completo |

## Installazione

1. Copia la cartella `l10n_it_pec` in `extra-addons/`
2. Riavvia Odoo: `docker restart odoo` (o equivalente)
3. Attiva modalità sviluppatore
4. App → Aggiorna lista app → Cerca "PEC" → Installa

### Dipendenze
- `account` (core Odoo 18)
- `l10n_it_edi` (localizzazione italiana EDI)
- `mail` (core Odoo 18)

## Configurazione

### Via Impostazioni (consigliato)
Impostazioni → Contabilità → PEC SDI

### Via Company
Impostazioni → Aziende → [la tua azienda] → Tab "PEC SDI"

### Parametri

| Campo | Descrizione | Esempio |
|---|---|---|
| Modalità PEC | disabled / demo / test / production | `demo` per iniziare |
| Indirizzo PEC | PEC mittente registrata SDI | `azienda@pec.it` |
| Server SMTP | Server PEC provider | `smtps.pec.aruba.it` |
| Porta SMTP | Porta SSL/TLS | `465` |
| Utente SMTP | Credenziali login | `azienda@pec.it` |
| Password SMTP | Password PEC | `***` |
| Server IMAP | Per ricezione notifiche | `imaps.pec.aruba.it` |
| Porta IMAP | Porta IMAPS | `993` |
| Indirizzo SDI | PEC destinatario SDI | `sdi01@pec.fatturapa.it` |

## Modalità operative

### Demo (dry-run)
- Genera l'XML FatturaPA completo
- Logga nel Chatter della fattura
- **NON invia nulla**
- NON cambia lo stato EDI
- Perfetto per test iniziali

### Test
- Invia realmente via PEC
- Usa l'indirizzo SDI di test (se configurato)
- Cambia stato EDI a "sent"
- Richiede accreditamento portale FatturePa

### Produzione
- Invia allo SDI ufficiale
- Flusso completo con notifiche

## Come testare (step by step)

### Step 1: Installazione e Demo
```
1. Installa il modulo
2. Vai in Impostazioni → Contabilità → PEC SDI
3. Seleziona "Demo (dry-run)"
4. Salva
5. Crea una fattura di vendita
6. Conferma la fattura
7. Clicca "👁 Anteprima XML"
8. Verifica l'XML nel Chatter
```

### Step 2: Test connessione
```
1. Configura credenziali SMTP PEC
2. Vai in Azienda → Tab PEC SDI
3. Clicca "🔌 Test connessione SMTP"
4. Configura credenziali IMAP
5. Clicca "🔌 Test connessione IMAP"
```

### Step 3: Test invio
```
1. Cambia modalità a "Test"
2. Configura indirizzo PEC SDI di test
3. Crea e conferma una fattura
4. Clicca "📨 Invia via PEC"
5. Verifica nel Chatter che l'invio sia avvenuto
```

## Notifiche SDI

Il cron job `PEC SDI: Controlla inbox PEC` gira ogni 15 minuti e:

1. Si connette via IMAP alla casella PEC
2. Cerca messaggi non letti da `@pec.fatturapa.it`
3. Identifica il tipo di notifica dall'allegato XML
4. Aggiorna lo stato EDI standard della fattura

### Mapping notifiche → stati

| Notifica SDI | Significato | Stato Odoo |
|---|---|---|
| RC | Ricevuta di Consegna | `forwarded` |
| NS | Notifica di Scarto | `rejected` |
| MC | Mancata Consegna | `forward_failed` |
| AT | Attestazione | `forwarded` |
| DT | Decorrenza Termini | `accepted_by_pa_partner_after_expiry` |
| NE (EC01) | Esito: Accettazione | `accepted_by_pa_partner` |
| NE (EC02) | Esito: Rifiuto | `rejected_by_pa_partner` |

## Struttura modulo

```
l10n_it_pec/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── res_company.py          # Configurazione PEC
│   ├── res_config_settings.py  # Esposizione in Impostazioni
│   ├── account_move.py         # CORE: override _l10n_it_edi_send
│   ├── account_move_send.py    # Integrazione wizard "Invia e Stampa"
│   └── pec_mail_handler.py     # Cron IMAP polling notifiche
├── wizard/
│   ├── __init__.py
│   ├── pec_send_wizard.py      # Wizard invio massivo
│   └── pec_send_wizard_views.xml
├── views/
│   ├── res_company_views.xml
│   ├── res_config_settings_views.xml
│   └── account_move_views.xml
├── security/
│   ├── res_groups.xml
│   └── ir.model.access.csv
├── data/
│   └── cron_data.xml
└── tests/
    ├── __init__.py
    └── test_pec.py
```

## Note tecniche importanti

### Odoo 18 vs Odoo 16/17
In Odoo 18, il sistema EDI italiano **non usa più** `account.edi.format` e `account.edi.document`. Il flusso passa per:
- `account.move._l10n_it_edi_send()` per l'invio
- `account.move.send._call_web_service_before_invoice_pdf_render()` per il wizard
- `l10n_it_edi_state` field su `account.move` per gli stati

Questo modulo si integra in questi punti esatti.

### Sicurezza
- Le credenziali PEC restano nel database Odoo (criptate)
- L'accesso alla configurazione richiede il gruppo "Gestore PEC SDI"
- Il cron IMAP usa connessione SSL

## Licenza

LGPL-3.0 — Copyright 2026 OdooManager.cloud
