# OdooManager - Sync Dettagli E-Fattura
## Guida operativa per utenti Odoo

**Versione modulo:** 18.0.3.0.0
**Ultima revisione:** Aprile 2026
**Autore:** Luigi Trubiani — OdooManager.cloud

---

## ⚠️ AVVERTENZA IMPORTANTE — Professionisti con Cassa Previdenziale

> **Se sei (o i tuoi clienti sono) un professionista con Cassa Previdenziale** (es. commercialista, avvocato, ingegnere, architetto, consulente del lavoro, geometra, notaio, medico), leggi attentamente questa sezione.
>
> Nel tab "Dettagli e-fattura" il modulo genera un **riepilogo per aliquota** (summary). Il campo "Aliquota IVA" del riepilogo, nella versione attuale v18.0.3.0.0, **include il valore di imposte NON IVA che hanno aliquota > 0**, come ad esempio la Cassa Previdenza (4%).
>
> Questo significa che se un forfettario consulente emette una fattura con:
> - Imposta "0% Forfettario" (N2.2) → OK, aliquota 0
> - Imposta "Cassa Previdenza Dottori Commercialisti" (4%) → **viene inclusa erroneamente nel calcolo dell'aliquota IVA**
>
> Il summary potrebbe mostrare "Aliquota 4%" invece di "Aliquota 0%".
>
> **Impatti da verificare:**
> - La trasmissione XML all'SDI **NON è impattata** (l'XML è generato dal core Odoo, non dal tab)
> - La Cassa Previdenza finisce correttamente nel blocco `<DatiCassaPrevidenziale>` dell'XML trasmesso
> - L'imponibile e il totale della fattura sono corretti
> - **Il tab "Dettagli e-fattura" potrebbe mostrare dati fuorvianti** sulle fatture con cassa previdenza
>
> **Cosa fare se sei un professionista con Cassa Previdenziale:**
> 1. Verifica il tab dopo aver emesso le prime fatture di prova
> 2. Se noti il valore 4% nell'aliquota IVA del summary, **contatta OdooManager.cloud per una versione adattata** del modulo
> 3. In attesa della versione adattata, il summary nel tab può risultare inaccurato, ma le fatture trasmesse restano fiscalmente corrette
>
> **Una versione futura del modulo affronterà questo caso specifico** separando correttamente Cassa Previdenziale dall'IVA nel calcolo del summary.

---

## Cosa fa questo modulo

Il modulo mantiene **sempre coerente** il tab "Dettagli e-fattura" delle tue fatture cliente italiane, assicurando che i dati mostrati nel tab siano sempre allineati con le righe reali della fattura.

Senza questo modulo, il tab mostra valori incoerenti:
- **Zero** per le fatture create da zero (non popolate automaticamente dal modulo OCA)
- **Dati stantii** per le fatture importate da XML e poi modificate (il modulo OCA legge dall'XML ma non riallinea alle modifiche successive)

## A chi serve

Il modulo è utile se sei:
- Un **forfettario italiano** che emette fatture elettroniche via SDI
- Una **PMI italiana** che usa Odoo 18 per la fatturazione
- Un **commercialista** che gestisce fatture di clienti in Odoo (leggi l'avvertenza sopra per il caso Cassa Previdenziale)

Il modulo è particolarmente utile se:
- Importi XML di fatture cliente da altri gestionali e poi le modifichi
- Crei fatture da zero e vuoi vedere i dettagli e-fattura popolati correttamente
- Vuoi presentare ai tuoi clienti un'interfaccia Odoo pulita e professionale

## Cosa vedrai dopo l'installazione

### Nel form della fattura cliente

Quando apri una fattura cliente in bozza, in alto vicino ai pulsanti "Conferma", "Annulla", ecc., appare un nuovo pulsante:

**"Ricalcola dettagli e-fattura"**

Questo pulsante è visibile solo se la fattura rispetta queste condizioni:
- Tipo cliente (fattura o nota di credito cliente)
- Stato "bozza"
- Paese Italia

### Nel tab "Dettagli e-fattura"

Il tab mostra ora dati coerenti con le righe della fattura. Le tabelle del tab sono protette da modifiche manuali (non vedi più il pulsante "Aggiungi riga" né le iconcine cestino) perché sono gestite automaticamente dal modulo.

Le sezioni Art.73, Arrotondamento e Stabile Organizzazione restano invariate — non vengono modificate dal modulo.

## Come funziona il sync automatico

Il modulo sincronizza il tab automaticamente nei seguenti momenti:

### 1. Quando crei una nuova fattura cliente
Non appena salvi una nuova fattura cliente italiana in bozza, il tab viene popolato con i dati delle righe.

### 2. Quando modifichi le righe di una fattura esistente
Non appena salvi le modifiche (pulsante Salva, cambio di vista, Ctrl+S, o al blur del campo), il tab si aggiorna con i nuovi dati.

### 3. Quando confermi la fattura
Alla conferma della fattura (click su "Conferma"), il modulo riallinea il tab prima della generazione dell'XML come ulteriore safety net.

### 4. Quando clicchi il pulsante manuale
Il pulsante "Ricalcola dettagli e-fattura" in alto permette di forzare esplicitamente il ricalcolo in caso di dubbi.

## Scenari d'uso tipici

### Scenario 1 — Forfettario emette fattura da zero

1. Crea una nuova fattura cliente
2. Aggiungi il cliente
3. Aggiungi una o più righe prodotto/servizio
4. Applica l'imposta "0% Forfettario" (natura N2.2)
5. Salva la fattura

**Risultato atteso nel tab "Dettagli e-fattura":**
- Imponibile e-fattura = somma delle righe
- Importo imposta e-fattura = 0
- Tabella con le righe della fattura
- Summary con 1 record (aliquota 0, natura N2.2)

Conferma la fattura per trasmetterla all'SDI.

### Scenario 2 — Import XML e successiva modifica

1. Dalle fatture cliente, clicca "Carica fattura" e carica un XML
2. Odoo popola automaticamente cliente, righe, imposte
3. Ora modifica una riga: aggiungi un prodotto, cambia un prezzo, correggi una quantità
4. Salva

**Risultato atteso:**
- Il tab "Dettagli e-fattura" si riallinea ai nuovi valori (non mostra più i valori vecchi dell'XML importato)

### Scenario 3 — Ritorno in bozza di fattura confermata

1. Apri una fattura già confermata
2. Clicca "Reimposta a bozza"
3. Modifica qualcosa
4. Salva

**Risultato atteso:**
- Il tab si aggiorna con i nuovi valori
- Puoi riconfermare serenamente

## Cosa NON fa il modulo

- **Non tocca i dati contabili reali** (righe account.move.line, scritture, bilanci)
- **Non modifica l'XML trasmesso all'SDI** (l'XML è generato dal core Odoo dalle righe reali, non dal tab)
- **Non modifica** i campi Art.73, Stabile Organizzazione, Arrotondamento (sono user-editable o readonly OCA)
- **Non tocca** le fatture passive/fornitore (preserva i dati XML ricevuti)
- **Non modifica** fatture già confermate in stato "posted"

## FAQ

**D: Se non clicco mai il pulsante "Ricalcola dettagli e-fattura", la fattura viene trasmessa correttamente all'SDI?**

R: Sì. L'XML trasmesso viene sempre generato dal core Odoo leggendo le righe reali della fattura. Il tab "Dettagli e-fattura" è solo una vista informativa, non influenza la trasmissione.

**D: Posso disinstallare il modulo senza rischi?**

R: Sì. Disinstallando il modulo:
- Il tab torna al comportamento originale (popolato solo da import XML, disallineato su modifiche)
- I dati storici restano nel database
- Le fatture già trasmesse non sono impattate

**D: Il modulo funziona sulle fatture fornitore (passive)?**

R: No per scelta. Le fatture passive mantengono i dati originali dell'XML ricevuto dal fornitore. Il modulo opera solo sulle fatture cliente.

**D: Che succede se clicco "Ricalcola dettagli e-fattura" su una fattura con sconti complessi o più imposte per riga?**

R: Il modulo considera la prima imposta IVA di ogni riga per determinare aliquota e natura. Per scenari molto complessi (più imposte IVA per riga), verifica il risultato e se necessario contatta OdooManager.cloud per un adattamento.

**D: Posso modificare manualmente le righe nel tab "Dettagli e-fattura"?**

R: No sulle fatture cliente, il modulo blocca queste modifiche perché i dati sono gestiti automaticamente. Se hai bisogno di modificare un dato del tab, modifica invece la riga corrispondente nel tab "Righe fattura": il tab si aggiorna di conseguenza.

**D: Cosa succede alla Cassa Previdenziale (4%) sulle fatture dei professionisti?**

R: Leggi attentamente l'**avvertenza all'inizio** di questo documento. In sintesi:
- La Cassa Previdenza finisce correttamente nel blocco `<DatiCassaPrevidenziale>` dell'XML (trasmissione OK)
- Nel tab del summary potrebbe comparire un valore di aliquota IVA errato (4%) — problema cosmetico, non fiscale
- Una versione futura del modulo gestirà correttamente questo caso

## Supporto

Per problemi, suggerimenti o richieste di adattamento specifico al tuo caso d'uso, contatta:

**Luigi Trubiani**
**OdooManager.cloud**
