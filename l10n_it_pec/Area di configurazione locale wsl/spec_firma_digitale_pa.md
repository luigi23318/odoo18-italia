---
name: SPEC - Firma digitale fatture PA (download/upload manuale)
description: Specifiche tecniche per implementare il flusso di firma digitale manuale delle fatture PA nel modulo l10n_it_pec
type: spec
created: 2026-03-31
---

# SPEC: Firma digitale fatture PA — Download/Upload manuale

## Contesto

Le fatture elettroniche verso la Pubblica Amministrazione richiedono obbligatoriamente la firma digitale qualificata (CAdES `.xml.p7m` o XAdES `.xml`). Per le fatture B2B/B2C la firma è facoltativa.

Questa feature aggiunge un flusso manuale: l'utente scarica l'XML, lo firma in locale con il proprio software di firma (Aruba Sign, GoSign, Namirial Sign, Dike...), e riallega il file firmato in Odoo per l'invio via PEC.

**Costo per il cliente: zero** — usa la firma digitale che già possiede.

## Principi architetturali (RISPETTARE)

1. **Solo le modifiche descritte in questa spec.** Non toccare file non elencati. Non aggiungere refactoring, cleanup, feature extra.
2. **Il modulo resta un layer di trasporto.** La firma è responsabilità dell'utente, Odoo non firma nulla.
3. **Coerenza con Opzione C** — `_l10n_it_edi_upload()` resta il punto di intercettazione. La firma cambia solo COSA viene inviato (`.p7m` vs `.xml`), non COME.
4. **Nessuna dipendenza Python aggiuntiva** per la firma. Nessuna libreria crittografica.

## Flusso utente

```
1. Utente crea fattura PA in Odoo
2. Conferma fattura → XML generato dallo standard Odoo (l10n_it_edi)
3. Clicca "Scarica XML per firma" → browser scarica il file XML
4. Firma il file in locale (software di firma del cliente)
5. Clicca "Carica XML firmato" → carica il file .xml.p7m (o .xml XAdES)
6. Odoo valida il file caricato
7. Stato si aggiorna a "Firmato, pronto per invio"
8. Invio PEC usa il file firmato al posto dell'XML originale
```

## Discriminazione fatture PA

Una fattura è considerata PA quando il campo `l10n_it_pa_index` (Codice IPA) è valorizzato E il codice destinatario è di 6 caratteri alfanumerici maiuscoli (le PA usano codici IPA di 6 caratteri, i privati usano codici di 7 caratteri o "0000000").

Implementazione del metodo helper:

```python
def _l10n_it_pec_is_pa_invoice(self):
    """Determina se la fattura è destinata a una Pubblica Amministrazione."""
    self.ensure_one()
    pa_index = self.l10n_it_pa_index or ''
    # Codici IPA della PA sono di 6 caratteri alfanumerici maiuscoli
    return bool(pa_index) and len(pa_index) == 6 and pa_index.isalnum() and pa_index.isupper()
```

**NOTA:** Verificare che il campo `l10n_it_pa_index` esista nel modello `account.move` nello standard Odoo 18 `l10n_it_edi`. Se il campo ha un nome diverso o non esiste, adattare. Il campo potrebbe anche chiamarsi `l10n_it_destination_code_type` o simile. Controllare lo standard prima di implementare.

---

## File da modificare

### 1. `models/account_move.py`

#### 1.1 Nuovo campo: `l10n_it_pec_signed_attachment_id`

```python
l10n_it_pec_signed_attachment_id = fields.Many2one(
    'ir.attachment',
    string="XML firmato digitalmente",
    copy=False,
    help="File XML firmato digitalmente (CAdES .p7m o XAdES .xml) da inviare allo SDI"
)
```

#### 1.2 Nuovo campo computed: `l10n_it_pec_signature_required`

```python
l10n_it_pec_signature_required = fields.Boolean(
    string="Firma digitale richiesta",
    compute='_compute_l10n_it_pec_signature_required',
    help="True se la fattura è destinata alla PA e richiede firma digitale"
)

@api.depends('l10n_it_pa_index')
def _compute_l10n_it_pec_signature_required(self):
    for move in self:
        move.l10n_it_pec_signature_required = move._l10n_it_pec_is_pa_invoice()
```

#### 1.3 Nuovo campo computed: `l10n_it_pec_signature_state`

```python
l10n_it_pec_signature_state = fields.Selection(
    selection=[
        ('not_required', 'Non richiesta'),
        ('awaiting', 'In attesa di firma'),
        ('signed', 'Firmato'),
    ],
    string="Stato firma digitale",
    compute='_compute_l10n_it_pec_signature_state',
)

@api.depends('l10n_it_pec_signature_required', 'l10n_it_pec_signed_attachment_id')
def _compute_l10n_it_pec_signature_state(self):
    for move in self:
        if not move.l10n_it_pec_signature_required:
            move.l10n_it_pec_signature_state = 'not_required'
        elif move.l10n_it_pec_signed_attachment_id:
            move.l10n_it_pec_signature_state = 'signed'
        else:
            move.l10n_it_pec_signature_state = 'awaiting'
```

#### 1.4 Metodo: `action_l10n_it_pec_download_xml`

Bottone per scaricare l'XML generato dallo standard, pronto per la firma.

```python
def action_l10n_it_pec_download_xml(self):
    """Scarica l'XML della fattura per la firma digitale in locale."""
    self.ensure_one()
    # Cercare l'attachment XML generato dallo standard l10n_it_edi
    # Il filename segue il pattern: IT<partita_iva>_<progressivo>.xml
    # L'attachment è legato alla fattura con res_model='account.move' e res_id=self.id
    # Filtrare per nome file che inizia con 'IT' e finisce con '.xml'
    attachment = self.env['ir.attachment'].search([
        ('res_model', '=', 'account.move'),
        ('res_id', '=', self.id),
        ('name', '=like', 'IT%.xml'),
    ], limit=1, order='create_date desc')

    if not attachment:
        raise UserError(_("Nessun file XML trovato per questa fattura. "
                          "Generare prima il file XML tramite 'Invia e Stampa'."))

    # Ritorna azione di download
    return {
        'type': 'ir.actions.act_url',
        'url': f'/web/content/{attachment.id}?download=true',
        'target': 'self',
    }
```

**NOTA IMPORTANTE:** Verificare come lo standard `l10n_it_edi` salva l'XML generato. Potrebbe essere:
- Un `ir.attachment` con `res_model='account.move'`
- Oppure salvato nel campo `l10n_it_edi_attachment_id` o simile
- Oppure generato on-the-fly in `_l10n_it_edi_send()`

Adattare la ricerca dell'attachment in base a come lo standard effettivamente lo gestisce. Se l'XML non è ancora stato generato (la fattura non è ancora passata per il flusso di invio), potrebbe essere necessario generarlo on-demand chiamando il metodo di generazione XML dello standard.

#### 1.5 Metodo: `action_l10n_it_pec_upload_signed`

Bottone per caricare il file firmato. Apre un wizard dedicato (vedi sezione wizard).

```python
def action_l10n_it_pec_upload_signed(self):
    """Apre il wizard per caricare il file XML firmato digitalmente."""
    self.ensure_one()
    return {
        'type': 'ir.actions.act_window',
        'name': _("Carica XML firmato"),
        'res_model': 'l10n_it_pec.upload.signed.wizard',
        'view_mode': 'form',
        'target': 'new',
        'context': {'default_move_id': self.id},
    }
```

#### 1.6 Metodo: `action_l10n_it_pec_remove_signed`

Bottone per rimuovere il file firmato (in caso di errore, l'utente vuole ricaricare).

```python
def action_l10n_it_pec_remove_signed(self):
    """Rimuove il file XML firmato per consentire un nuovo upload."""
    self.ensure_one()
    if self.l10n_it_pec_signed_attachment_id:
        self.l10n_it_pec_signed_attachment_id.unlink()
        self.l10n_it_pec_signed_attachment_id = False
```

#### 1.7 Modifica a `_l10n_it_edi_upload(files)`

**Questa è la modifica chiave.** Dentro `_l10n_it_edi_upload`, PRIMA dell'invio SMTP, se la fattura è PA e ha un file firmato allegato, sostituire il contenuto e il filename.

```python
# DENTRO _l10n_it_edi_upload, PRIMA dell'invio SMTP PEC:
# Pseudocodice della logica da aggiungere:

for filename, xml_content in files.items():
    # Se fattura PA con file firmato, usare il file firmato
    if self._l10n_it_pec_is_pa_invoice() and self.l10n_it_pec_signed_attachment_id:
        signed_att = self.l10n_it_pec_signed_attachment_id
        xml_content = base64.b64decode(signed_att.datas)
        filename = signed_att.name  # es: IT01234567890_00001.xml.p7m
    elif self._l10n_it_pec_is_pa_invoice() and not self.l10n_it_pec_signed_attachment_id:
        # Fattura PA senza firma: bloccare l'invio
        return {filename: {
            'error': _("Firma digitale richiesta"),
            'error_description': _("Le fatture verso la PA richiedono la firma digitale. "
                                    "Scaricare l'XML, firmarlo e ricaricare il file firmato.")
        }}

    # ... continua con l'invio SMTP PEC esistente usando xml_content e filename ...
```

**ATTENZIONE:** Non ristrutturare il metodo `_l10n_it_edi_upload` esistente. Aggiungere SOLO questa logica nel punto giusto, prima che `xml_content` e `filename` vengano usati per costruire l'email PEC.

---

### 2. Nuovo file: `wizard/pec_upload_signed_wizard.py`

Wizard TransientModel per il caricamento del file firmato con validazione.

```python
class PecUploadSignedWizard(models.TransientModel):
    _name = 'l10n_it_pec.upload.signed.wizard'
    _description = 'Upload XML firmato digitalmente'

    move_id = fields.Many2one('account.move', required=True)
    signed_file = fields.Binary(string="File XML firmato", required=True)
    signed_filename = fields.Char(string="Nome file")

    def action_upload(self):
        """Valida e allega il file firmato alla fattura."""
        self.ensure_one()

        if not self.signed_file:
            raise UserError(_("Selezionare un file."))

        filename = self.signed_filename or ''

        # --- VALIDAZIONE FILENAME ---
        # Accettare solo .xml.p7m (CAdES) o .xml (XAdES)
        if not (filename.lower().endswith('.xml.p7m') or filename.lower().endswith('.xml')):
            raise UserError(_(
                "Formato file non valido. Sono accettati solo:\n"
                "- .xml.p7m (firma CAdES)\n"
                "- .xml (firma XAdES enveloped)"
            ))

        # --- VALIDAZIONE CONTENUTO P7M ---
        file_content = base64.b64decode(self.signed_file)

        if filename.lower().endswith('.xml.p7m'):
            # Verificare header ASN.1/DER di un file PKCS#7
            # I file CAdES/PKCS7 in formato DER iniziano con 0x30 (SEQUENCE tag)
            if len(file_content) < 2 or file_content[0] != 0x30:
                raise UserError(_(
                    "Il file non sembra essere un file .p7m valido. "
                    "Assicurarsi di aver firmato il file con il software di firma digitale."
                ))

        # --- VALIDAZIONE CORRISPONDENZA FILENAME ---
        # Il nome del file firmato deve corrispondere al filename della fattura
        # es: IT01234567890_00001.xml.p7m deve corrispondere a IT01234567890_00001.xml
        expected_xml_name = self._get_expected_xml_filename()
        if expected_xml_name:
            base_name = filename
            if base_name.lower().endswith('.p7m'):
                base_name = base_name[:-4]  # rimuove .p7m → resta .xml
            if base_name != expected_xml_name:
                raise UserError(_(
                    "Il nome del file firmato non corrisponde alla fattura.\n"
                    "Atteso: %(expected)s\n"
                    "Ricevuto: %(received)s",
                    expected=expected_xml_name,
                    received=base_name,
                ))

        # --- CREAZIONE ATTACHMENT ---
        # Rimuovere eventuale attachment firmato precedente
        if self.move_id.l10n_it_pec_signed_attachment_id:
            self.move_id.l10n_it_pec_signed_attachment_id.unlink()

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': self.signed_file,
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'type': 'binary',
        })

        self.move_id.l10n_it_pec_signed_attachment_id = attachment.id

        return {'type': 'ir.actions.act_window_close'}

    def _get_expected_xml_filename(self):
        """Recupera il filename XML atteso dalla fattura."""
        # Cercare l'attachment XML generato per questa fattura
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.move_id.id),
            ('name', '=like', 'IT%.xml'),
        ], limit=1, order='create_date desc')
        return attachment.name if attachment else False
```

---

### 3. Nuovo file: `wizard/pec_upload_signed_wizard_views.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_pec_upload_signed_wizard_form" model="ir.ui.view">
        <field name="name">l10n_it_pec.upload.signed.wizard.form</field>
        <field name="model">l10n_it_pec.upload.signed.wizard</field>
        <field name="arch" type="xml">
            <form string="Carica XML firmato">
                <group>
                    <p class="text-muted">
                        Caricare il file XML firmato digitalmente (formato CAdES .xml.p7m o XAdES .xml).
                        Il file deve corrispondere all'XML della fattura.
                    </p>
                    <field name="move_id" invisible="1"/>
                    <field name="signed_file" filename="signed_filename"/>
                    <field name="signed_filename" invisible="1"/>
                </group>
                <footer>
                    <button string="Carica" name="action_upload" type="object" class="btn-primary"/>
                    <button string="Annulla" class="btn-secondary" special="cancel"/>
                </footer>
            </form>
        </field>
    </record>
</odoo>
```

---

### 4. Modifica: `views/account_move_views.xml`

Aggiungere nella vista form della fattura, nella sezione dove sono già presenti i bottoni PEC, i seguenti elementi. Posizionarli DOPO i bottoni PEC esistenti, nella stessa area.

#### 4.1 Blocco informativo firma digitale (solo per fatture PA)

```xml
<!-- Blocco firma digitale PA — visibile solo se la fattura richiede firma -->
<div attrs="{'invisible': [('l10n_it_pec_signature_required', '=', False)]}">
    <field name="l10n_it_pec_signature_required" invisible="1"/>
    <field name="l10n_it_pec_signature_state" invisible="1"/>
    <field name="l10n_it_pec_signed_attachment_id" invisible="1"/>

    <!-- Stato: in attesa di firma -->
    <div class="alert alert-warning mb-0"
         attrs="{'invisible': [('l10n_it_pec_signature_state', '!=', 'awaiting')]}">
        <strong>Firma digitale richiesta</strong> —
        Fattura PA: scaricare l'XML, firmarlo e ricaricare.
    </div>

    <!-- Stato: firmato -->
    <div class="alert alert-success mb-0"
         attrs="{'invisible': [('l10n_it_pec_signature_state', '!=', 'signed')]}">
        <strong>Firmato digitalmente</strong> —
        <field name="l10n_it_pec_signed_attachment_id" widget="many2one" readonly="1" nolabel="1" class="d-inline"/>
    </div>

    <!-- Bottoni firma -->
    <div class="mt-2">
        <button name="action_l10n_it_pec_download_xml"
                string="Scarica XML per firma"
                type="object"
                class="btn-link"
                icon="fa-download"
                attrs="{'invisible': [('l10n_it_pec_signature_state', '!=', 'awaiting')]}"/>
        <button name="action_l10n_it_pec_upload_signed"
                string="Carica XML firmato"
                type="object"
                class="btn-link"
                icon="fa-upload"
                attrs="{'invisible': [('l10n_it_pec_signature_state', '!=', 'awaiting')]}"/>
        <button name="action_l10n_it_pec_remove_signed"
                string="Rimuovi firma"
                type="object"
                class="btn-link text-danger"
                icon="fa-trash"
                confirm="Rimuovere il file firmato?"
                attrs="{'invisible': [('l10n_it_pec_signature_state', '!=', 'signed')]}"/>
    </div>
</div>
```

**NOTA su attrs vs domain in Odoo 18:** Verificare la sintassi corretta per la visibilità condizionale in Odoo 18 CE. In Odoo 17+ potrebbe essere necessario usare `column_invisible`, `readonly`, `invisible` come attributi Python sul campo o usare la nuova sintassi. Adattare se `attrs` non è più supportato.

---

### 5. Modifica: `wizard/__init__.py`

Aggiungere l'import del nuovo wizard:

```python
from . import pec_upload_signed_wizard
```

---

### 6. Modifica: `security/ir.model.access.csv`

Aggiungere la riga ACL per il nuovo wizard:

```csv
access_l10n_it_pec_upload_signed_wizard,l10n_it_pec.upload.signed.wizard,model_l10n_it_pec_upload_signed_wizard,base.group_user,1,1,1,0
```

---

### 7. Modifica: `__manifest__.py`

Aggiungere il nuovo file vista del wizard in `data`:

```python
'data': [
    # ... file esistenti ...
    'wizard/pec_upload_signed_wizard_views.xml',
],
```

---

## File da NON modificare

- `models/res_company.py` — Nessuna configurazione a livello company per questa feature
- `models/res_config_settings.py` — Nessuna setting aggiuntiva
- `models/pec_mail_handler.py` — Il parsing delle notifiche SDI non cambia
- `views/res_company_views.xml` — Nessuna modifica alla vista company
- `views/res_config_settings_views.xml` — Nessuna modifica alle settings
- `wizard/pec_send_wizard.py` — Il wizard invio massivo non è toccato
- `data/cron_data.xml` — Il cron non è toccato
- `tests/test_pec.py` — Non aggiungere test in questa fase

---

## Gestione notifiche SDI con file firmato

Quando lo SDI riceve un file `.xml.p7m`, le notifiche di ritorno (RC, NS, MC, AT, NE, DT) faranno riferimento al filename `.xml.p7m`. Il parsing delle notifiche in `pec_mail_handler.py` usa il `NomeFile` dalla notifica XML per associare la risposta alla fattura.

**Verifica necessaria:** Controllare se `pec_mail_handler.py` fa match sul filename per associare la notifica alla fattura. Se sì, il match deve funzionare anche con il suffisso `.p7m`. Se il match è basato sulla transaction (Message-ID PEC), non serve nessuna modifica.

Se il match è basato sul filename, aggiungere logica per normalizzare: se il filename nella notifica SDI termina con `.xml.p7m`, cercare anche senza `.p7m`.

**NOTA:** Questa verifica va fatta DOPO aver implementato le modifiche principali. Se serve modifica al mail handler, farla come intervento separato e minimale.

---

## Riepilogo file toccati

| File | Azione |
|------|--------|
| `models/account_move.py` | Aggiungere campi, metodi, logica in `_l10n_it_edi_upload` |
| `views/account_move_views.xml` | Aggiungere blocco firma nella form fattura |
| `wizard/__init__.py` | Aggiungere import nuovo wizard |
| `wizard/pec_upload_signed_wizard.py` | **NUOVO** — Wizard upload file firmato |
| `wizard/pec_upload_signed_wizard_views.xml` | **NUOVO** — Vista wizard |
| `security/ir.model.access.csv` | Aggiungere riga ACL wizard |
| `__manifest__.py` | Aggiungere file vista wizard |

**Totale: 5 file modificati + 2 file nuovi**

---

## Checklist pre-implementazione

Prima di scrivere codice, Claude Code deve:

1. [ ] Leggere `models/account_move.py` attuale per capire la struttura di `_l10n_it_edi_upload`
2. [ ] Verificare come lo standard `l10n_it_edi` salva l'XML generato (campo attachment o generazione on-the-fly)
3. [ ] Verificare il nome esatto del campo codice destinatario PA (`l10n_it_pa_index` o altro)
4. [ ] Verificare la sintassi `attrs` vs nuova sintassi Odoo 18 per visibilità condizionale nelle viste XML
5. [ ] Verificare se `pec_mail_handler.py` fa match su filename o su transaction per associare le notifiche SDI
6. [ ] Leggere `wizard/__init__.py` per capire la struttura import attuale
7. [ ] Leggere `security/ir.model.access.csv` per capire il formato delle righe esistenti
8. [ ] Leggere `__manifest__.py` per capire dove aggiungere il file vista

---

## Note per Claude Code

- **LEGGERE SEMPRE i file PRIMA di modificarli.** Non assumere la struttura.
- **FARE SOLO le modifiche descritte in questa spec.** Non aggiungere refactoring, miglioramenti, cleanup.
- **Indicare a fine lavoro la lista esatta dei file modificati.**
- **Se qualcosa nella spec non è compatibile con il codice esistente** (es: un campo non esiste, un metodo ha firma diversa), adattare la spec al codice reale e documentare la differenza nel commit message.
