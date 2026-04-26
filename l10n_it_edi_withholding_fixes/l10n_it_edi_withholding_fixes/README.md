# Italian E-invoice Withholding - Bug Fixes

Workaround temporaneo per bug noti del modulo `l10n_it_edi_withholding` di Odoo S.A. relativi alla generazione del file XML FatturaPA in presenza di ritenute d'acconto.

## Origine architetturale

Questo modulo replica concettualmente la funzione storica del modulo OCA `l10n_it_fatturapa_out_wt` (versioni 8.0 - 16.0), che per anni ha corretto i bug di generazione XML FatturaPA quando ci sono ritenute d'acconto.

Quel modulo OCA storico **non è disponibile per Odoo 18** e **non è compatibile** con il modulo standard `l10n_it_edi` di Odoo S.A. (sono ecosistemi mutuamente esclusivi). La strategia OCA per Odoo 18 è infatti quella di estendere `l10n_it_edi` con moduli `l10n_it_edi_*_extension`, ma al momento (aprile 2026) non esiste ancora un'estensione che fixi i bug delle ritenute.

Questo modulo colma quel vuoto temporaneo per chi usa la stack Odoo S.A. (`l10n_it_edi` + `l10n_it_edi_withholding`).

## Filosofia di progettazione

### Auto-disattivante

Ogni fix verifica autonomamente se intervenire, basandosi sul confronto tra valore calcolato dal modulo standard e valore atteso secondo le specifiche FatturaPA. Quando i bug saranno corretti upstream da Odoo S.A. (o da un futuro modulo OCA `l10n_it_edi_withholding_extension`), i fix smetteranno di intervenire automaticamente.

In tal caso:

- Il modulo può essere disinstallato per pulizia
- Oppure può rimanere installato senza alcun impatto: i fix vedranno che il valore è già corretto e non interverranno

### Diagnostico

Ogni invocazione di un fix produce un log a livello INFO che documenta lo stato:

- `Fix ... APPLICATO`: il fix è intervenuto, con dettaglio dei valori prima e dopo
- `Fix ... NON necessario`: il fix non è intervenuto perché il valore era già corretto (segnale che il bug è stato fixato upstream)
- `Fix ... NON applicato`: il fix non è applicabile in questo caso (es. fattura senza ritenute)

I log sono recuperabili con:

```bash
docker logs --tail 500 odoo18-app 2>&1 | grep "l10n_it_edi_withholding_fixes"
```

### Mirato

Il modulo non riscrive funzionalità che `l10n_it_edi_withholding` già gestisce correttamente. Si limita a correggere bug specifici e verificati. Ogni fix è una funzione separata con scope ben delimitato.

### Estensibile

L'architettura permette di aggiungere nuovi fix senza riscrivere il modulo: basta aggiungere una nuova funzione `_l10n_it_edi_fix_xxx()` e chiamarla dall'override di `_l10n_it_edi_get_values()`.

## Bug coperti

### Fix #1: ImportoTotaleDocumento errato in presenza di ritenute

**Sintomo**: il tag `<ImportoTotaleDocumento>` del XML FatturaPA contiene il netto ritenute invece del lordo richiesto dalle specifiche.

**Esempio reale** (agente di commercio in regime forfettario):

| Voce | Importo |
|---|---|
| Provvigione | 1000.00 € |
| IVA 0% Forfettario (N2.2) | 0.00 € |
| ENASARCO -8.5% | -85.00 € |
| **Atteso `<ImportoTotaleDocumento>`** | **1000.00 €** ✅ |
| **Bug `<ImportoTotaleDocumento>`** | **915.00 €** ❌ |

**Soluzione**: il fix usa il campo `l10n_it_amount_before_withholding_signed` già calcolato dal modulo `l10n_it_edi_withholding` per popolare correttamente il tag XML.

**Riferimenti normativi**:

- [Agenzia delle Entrate - FAQ Fatturazione Elettronica](https://www.fatturapa.gov.it)
- Specifica tecnica FatturaPA 1.6.1, paragrafo 2.1.1.9
- Studio Simonetti: "Regime forfettario: la somma dell'imponibile e della trattenuta Enasarco darà il totale fattura"
- Fattura.it: "una fattura con ENASARCO presenterà l'importo lordo della provvigione"

**Casistiche coperte**:

- Agente forfettario con ENASARCO (no ritenuta IRPEF)
- Agente ordinario con IVA 22% + ENASARCO + ritenuta IRPEF 23%/50%
- Professionista con cassa previdenziale + ritenuta IRPEF
- Qualunque altra fattura con almeno una ritenuta d'acconto

## Installazione

1. Copiare la cartella `l10n_it_edi_withholding_fixes` nella propria directory custom-addons:

   ```bash
   /home/odoo/odoo-docker/custom-addons/odoo18-italia/l10n_it_edi_withholding_fixes/
   ```

2. Riavviare Odoo:

   ```bash
   docker compose restart odoo18-app
   ```

3. Aggiornare la lista app dall'UI: **App → Aggiorna lista app**.

4. Cercare `l10n_it_edi_withholding_fixes` e installarlo.

## Verifica funzionamento

Dopo l'installazione, generare l'XML di una fattura con ritenute (es. cliente con ENASARCO) e controllare i log:

```bash
docker logs --tail 200 odoo18-app 2>&1 | grep "l10n_it_edi_withholding_fixes"
```

Si dovrebbe vedere uno di questi messaggi:

- `Fix ImportoTotaleDocumento APPLICATO a FATT/...` → il fix è intervenuto, il bug era presente
- `Fix ImportoTotaleDocumento NON necessario per FATT/...` → il fix non era necessario, il valore era già corretto

In entrambi i casi l'XML generato avrà `<ImportoTotaleDocumento>` corretto (lordo ritenute).

## Disinstallazione

Quando il bug sarà corretto upstream e si vorrà rimuovere il modulo:

1. **App → cercare `l10n_it_edi_withholding_fixes` → Disinstalla**

In alternativa, il modulo può rimanere installato a tempo indeterminato senza impatto sulla generazione XML, perché si auto-disattiva quando il bug non è presente.

## Compatibilità

- Odoo 18.0 Community Edition e Enterprise Edition
- Richiede `l10n_it_edi_withholding` (modulo Odoo S.A. standard, già autoinstallato in localizzazione italiana)
- Compatibile con `l10n_it_edi_extension` di OCA (qualsiasi versione)
- Compatibile con moduli custom che estendono `account.move._l10n_it_edi_get_values()` (gli override vengono applicati in catena tramite `super()`)

## Licenza

AGPL-3 (coerente con la licenza dei moduli OCA italiani)

## Autore

Luigi Trubiani / OdooManager.cloud  
[https://odoomanager.cloud](https://odoomanager.cloud)

## Storia delle modifiche

- **18.0.1.0.0** (aprile 2026): Prima release. Fix per `<ImportoTotaleDocumento>` con ritenute.
