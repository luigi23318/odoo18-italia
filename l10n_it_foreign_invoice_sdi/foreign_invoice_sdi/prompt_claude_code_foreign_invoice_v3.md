# PROMPT PER CLAUDE CODE
# Modulo Odoo 18 CE: l10n_it_foreign_invoice_sdi
# Modulo UNICO per gestione fatture estere passive
# Doppio motore di estrazione: Tesseract OCR locale + A-Cube API cloud
# Versione definitiva — Marzo 2026

---

## AMBIENTE DI LAVORO

Stai lavorando in LOCALE sul PC dello sviluppatore (Windows).
Il modulo va creato nella directory GitHub locale dello sviluppatore:

```
C:\Users\luigi\Documents\GitHub\l10n_it_foreign_invoice_sdi\
```

Crea questa cartella se non esiste e scrivi tutti i file del modulo al suo interno.

Lo sviluppatore usa GitHub Desktop per fare push del codice. Il deploy sul server Aruba Cloud PRO (dove gira Odoo 18 in Docker) avviene separatamente tramite git pull + riavvio container.

**NON tentare di:**
- Collegarti via SSH a server remoti
- Riavviare Docker o servizi
- Installare pacchetti di sistema
- Eseguire comandi Odoo

**Il tuo compito è SOLO scrivere i file del modulo** nella directory locale. Lo sviluppatore si occuperà del deploy e del test.

---

## CONTESTO DEL PROGETTO

Devi sviluppare un **modulo Odoo 18 Community Edition nativo unico** chiamato `l10n_it_foreign_invoice_sdi`.

Il modulo gestisce il flusso completo delle fatture estere passive per le PMI italiane, con **due motori di estrazione intercambiabili** selezionabili dall'operatore nelle Impostazioni:
- **Tesseract OCR locale**: pdfplumber + Tesseract + invoice2data con template YAML. Gratuito, privacy totale, nessun dato esce dal server.
- **A-Cube API cloud**: estrazione intelligente via API A-Cube con AI. Non richiede template. Dati elaborati nei server A-Cube (EU).

Il flusso end-to-end è:
1. Upload PDF fattura estera (singolo o batch)
2. Estrazione dati dal PDF (motore scelto nelle impostazioni)
3. Revisione obbligatoria da parte dell'operatore
4. Generazione XML FatturaPA (TD17/TD18/TD19)
5. Validazione XSD dell'XML
6. Invio allo SDI via Aruba Fatturazione Elettronica Premium API
7. Tracking notifiche SDI tramite cron job
8. Registrazione contabile con doppia registrazione IVA per reverse charge
9. Download XML singolo o ZIP batch sul PC dell'operatore

L'ambiente di produzione è Odoo 18 CE con localizzazione italiana (`l10n_it`), su Ubuntu 24.04, deployato via Docker su Aruba Cloud PRO.

---

## ISTRUZIONE CRITICA: LEGGI IL CODICE SORGENTE PRIMA DI SCRIVERE

**Prima di scrivere qualsiasi codice del modulo**, leggi e studia i seguenti file dal codice sorgente di Odoo 18. Se il codice sorgente Odoo non è disponibile localmente, scaricalo da GitHub (github.com/odoo/odoo, branch 18.0):

```
# Modello fattura — capire come creare account.move correttamente
addons/account/models/account_move.py
addons/account/models/account_move_line.py

# Come Odoo 18 gestisce le tasse
addons/account/models/account_tax.py

# Localizzazione italiana — campi specifici IT
addons/l10n_it/models/

# EDI — pattern per invio/ricezione documenti elettronici
addons/account_edi/models/
addons/account_edi_proxy_client/models/

# Peppol — modello di riferimento per integrazione con servizio esterno
addons/account_peppol/models/

# Impostazioni — come aggiungere configurazioni nel settings
addons/account/models/res_config_settings.py

# Report QWeb — come creare report PDF
addons/account/report/

# Wizard — pattern per wizard di importazione
addons/account/wizard/
```

**Non inventare pattern** — replica quelli che trovi nel codice sorgente di Odoo 18.

---

## DOCUMENTAZIONE TECNICA ALLEGATA

Hai ricevuto 3 documenti Word (.docx). Leggili per il contesto, MA le istruzioni in questo prompt hanno la **PRECEDENZA** dove ci sono differenze.

- `specifica_tecnica_v3_modulo_unico.docx` — Specifica principale: architettura, modelli dati, flussi, menu, impostazioni, reportistica, piano sprint
- `specifica_tesseract_invoice2data_v2.docx` — Dettaglio motore Tesseract: OCR, template YAML, i 12 template pre-inclusi
- `specifica_acube_estrazione_v1.docx` — Dettaglio motore A-Cube: API estrazione AI, mapping campi, gestione errori

---

## ARCHITETTURA: MODULO UNICO CON DOPPIO MOTORE

Un solo modulo. L'operatore sceglie il motore nelle Impostazioni con un radio button. Il flusso dopo l'estrazione è identico.

### Struttura file

```
l10n_it_foreign_invoice_sdi/
├── __init__.py
├── __manifest__.py                    # depends: ['account', 'l10n_it']
├── models/
│   ├── __init__.py
│   ├── foreign_invoice_import.py      # Modello principale singola fattura
│   ├── foreign_invoice_import_line.py # Righe dettaglio
│   ├── foreign_invoice_batch.py       # Batch elaborazione
│   ├── fatturapa_xml_generator.py     # Generatore XML FatturaPA v1.2.3
│   ├── aruba_sdi_service.py           # Client Aruba Premium API
│   └── res_config_settings.py         # Configurazione motore + credenziali
├── services/
│   ├── __init__.py
│   ├── ocr_service.py                 # pdfplumber + Tesseract OCR
│   ├── extraction_service.py          # invoice2data wrapper
│   └── acube_extraction_service.py    # Client A-Cube API estrazione
├── wizards/
│   ├── __init__.py
│   ├── import_single_wizard.py        # Upload singolo PDF
│   └── import_batch_wizard.py         # Upload multiplo PDF / ZIP
├── report/
│   ├── batch_control_report.py        # Report QWeb controllo batch
│   ├── batch_control_report.xml       # Template QWeb
│   └── batch_summary_xlsx.py          # Export Excel
├── views/
│   ├── foreign_invoice_import_views.xml
│   ├── foreign_invoice_batch_views.xml
│   ├── res_config_settings_views.xml
│   └── menuitems.xml                  # Solo 2 voci sotto Fatture fornitori
├── data/
│   ├── templates/                     # 12 template YAML (file statici)
│   │   ├── aws.yml
│   │   ├── google_cloud.yml
│   │   ├── google_workspace.yml
│   │   ├── microsoft_azure.yml
│   │   ├── microsoft_365.yml
│   │   ├── hetzner.yml
│   │   ├── ovhcloud.yml
│   │   ├── meta_facebook_ads.yml
│   │   ├── stripe.yml
│   │   ├── alibaba_aliexpress.yml
│   │   ├── shopify.yml
│   │   └── airbnb.yml
│   ├── ir_cron_data.xml
│   └── ir_sequence_data.xml
├── security/
│   ├── ir.model.access.csv
│   └── foreign_invoice_security.xml
└── static/description/
    └── icon.png
```

### Dipendenze
```python
# __manifest__.py
'depends': ['account', 'l10n_it'],
```
Nessun altro modulo custom.

---

## MENU E NAVIGAZIONE

### Solo 2 voci aggiunte sotto Fatture fornitori

```
Contabilità > Fatture fornitori
  ├── Fatture            (standard Odoo — NON TOCCATO)
  ├── Note di credito    (standard Odoo — NON TOCCATO)
  ├── Pagamenti          (standard Odoo — NON TOCCATO)
  ├── ────────────────── (separatore)
  ├── Importa fattura estera da PDF          (AGGIUNTO — wizard singolo)
  └── Importa fatture estere da PDF (batch)  (AGGIUNTO — wizard batch)
```

NESSUN ALTRO MENU. Tutto il resto è tab e pulsanti dentro le viste.

### Vista fattura singola — tab:
- Dati estratti / PDF originale / XML generato / Stato SDI / Registrazione contabile
- Pulsanti: Estrai dati, Valida, Genera XML, Invia al SDI, Scarica XML, Scarica PDF originale

### Vista batch — tab:
- Fatture (kanban per stato + contatori) / Report controllo / Dashboard
- Pulsanti: Applica default, Valida tutto, Genera tutti XML, Invia tutti al SDI, Scarica ZIP XML, Scarica report Excel

---

## IMPOSTAZIONI

Sezione "Acquisizione fatture in PDF" in Impostazioni → Contabilità.
Radio button in cima: Tesseract OCR locale / A-Cube API.
I campi sotto cambiano dinamicamente (attrs/invisible condizionale).

### Con Tesseract:
- Lingue OCR: default "ita+eng+deu+fra+spa"
- Usa template built-in: Boolean, default True
- Auto-estrazione al caricamento: Boolean, default True
- Invio SDI attivo: Boolean + credenziali Aruba Premium + ambiente + codice destinatario + polling

### Con A-Cube:
- Email + Password + Ambiente A-Cube
- Invio automatico dopo validazione: Boolean
- Frequenza polling notifiche

---

## MODELLI DATI

### foreign.invoice.import
Stati: bozza → testo_estratto → dati_estratti → nessun_template → in_revisione → validato → xml_generato → inviato_sdi → consegnato → scartato → registrato

Campi: name, state, extraction_engine, batch_id, pdf_attachment_id, xml_attachment_id, raw_text, template_matched, tipo_documento, supplier_name, supplier_vat, supplier_country_id, partner_id, invoice_number, invoice_date, reception_date, currency_id, amount_untaxed, amount_tax_foreign, amount_total, it_tax_id, natura_code, description_type, line_ids, sdi_state, sdi_id, sdi_filename, account_move_id, validation_errors

### foreign.invoice.import.line
Campi: import_id, description, quantity, unit_price, line_total, tax_rate_foreign

### foreign.invoice.batch
Campi: name, state, reception_date_default, tipo_documento_default, it_tax_id_default, natura_code_default, invoice_ids
Compute: total_invoices, total_matched, total_unmatched, total_validated, total_errors, total_amount, total_sent_sdi, total_delivered_sdi, total_rejected_sdi

Dettagli completi nei documenti Word allegati.

---

## SERVIZI DI ESTRAZIONE

Architettura a strategia — action_extract() legge il motore configurato e delega:
- Tesseract: pdfplumber → testo → invoice2data → campi (o stato nessun_template)
- A-Cube: PDF → API cloud → JSON → campi (match sempre)

Template YAML: 12 file statici in data/templates/. NON gestiti da Odoo.

---

## GENERAZIONE XML FATTURAPA

Schema v1.2.3. TD17/TD18/TD19.
SoggettoEmittente="CC", CodiceDestinatario="XXXXXXX", Data=data ricezione.
Validazione XSD con lxml SEMPRE prima del salvataggio.
Download XML su PC tramite pulsante (controller /web/content standard Odoo).

---

## INVIO SDI VIA ARUBA PREMIUM API

A-Cube è usato SOLO per estrazione. L'invio SDI è SEMPRE Aruba Premium (o download manuale).

Endpoint: /auth/signin, /services/invoice/upload, /services/notification/out/getByFilename
Multicedente: /auth/multicedenti, /auth/switchAccount
Cron job polling notifiche ogni N minuti (configurabile).

---

## REGISTRAZIONE CONTABILE

account.move (in_invoice) con doppia registrazione IVA reverse charge.
USA I METODI STANDARD di Odoo 18 — leggi account_peppol e account_edi come riferimento.

---

## REGOLE DI SVILUPPO

1. LEGGI codice sorgente Odoo 18 prima di scrivere.
2. Non sovrascrivere metodi core di account.move.
3. Credenziali in ir.config_parameter.
4. Timeout 30s, retry backoff 5xx, no retry 4xx.
5. Logging con _logger su ogni operazione SDI.
6. Batch: sincrono < 20 PDF, asincrono via cron per batch grandi.
7. Eccezioni per singolo record nel batch.
8. Python 3.11+, nomi in inglese, UI in italiano.
9. Type hints. Odoo coding guidelines.

---

## PROCEDURA

Sviluppa tutti gli STEP dal 1 al 9 in sequenza, creando tutti i file nella directory locale:

1. Struttura base e modelli dati
2. Servizi di estrazione (Tesseract + A-Cube)
3. Viste fattura singola (form con tab + pulsanti)
4. Batch (wizard + form con tab + azioni massive)
5. Generazione XML FatturaPA
6. Reportistica (report QWeb + Excel + dashboard dentro tab batch)
7. Invio SDI via Aruba Premium
8. Registrazione contabile
9. Impostazioni (radio button motore + config dinamica)

---

## CONTESTO NORMATIVO

- TD17: servizi da fornitori esteri UE e extra-UE (reverse charge)
- TD18: beni intracomunitari da fornitori UE spediti dall'estero
- TD19: beni già in Italia da fornitore estero
- Scadenza: entro il 15 del mese successivo (TD17/TD18), 12 giorni per TD19
