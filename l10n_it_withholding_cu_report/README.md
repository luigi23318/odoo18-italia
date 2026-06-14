# ITA - Ritenute per percipiente (dettaglio CU)

Aggiunge in **Contabilità → Reporting → "Ritenute per percipiente (CU)"** un
registro di dettaglio delle ritenute d'acconto, raggruppabile per **percipiente**,
**causale/ritenuta** e **anno**. È la base operativa per la Certificazione Unica
(non genera il file telematico CU, che resta in capo al commercialista / precompilato).

## Cosa mostra

- Le ritenute **realizzate per cassa**: prende le righe delle scritture *Tax Cash
  Basis* generate al pagamento/incasso, sui **conti definitivi** (es. 1609/2602/2603...).
  Questo evita il doppio conteggio con il conto di transizione (appoggio).
- **Entrambe le direzioni**:
  - *subite* (vendite, `type_tax_use = sale`) → ritenute che hai subìto dai tuoi clienti sostituti;
  - *operate* (acquisti, `type_tax_use = purchase`) → ritenute che hai operato come sostituto.
  Usa i filtri "subite" / "operate" nella barra di ricerca per separarle.

Vista **pivot** (default: percipiente × ritenuta, colonne per anno, misure
**imponibile** e **ritenuta**) e vista **lista** (dettaglio riga per riga, export
Excel nativo di Odoo).

## Note tecniche

- Implementato come **vista SQL read-only** (`account.move.line` proiettato in
  `l10n.it.withholding.cu.report`): **nessun dato persistito**, nessun nuovo campo sui
  modelli standard. Indipendente dal piano dei conti (funziona anche con
  `l10n_it_pdcodm`), perché filtra per tipo ritenuta della tax e non per codice conto.
- Sorgente: le righe "imposta" (`tax_line_id` = ritenuta) delle scritture *Tax Cash
  Basis* generate al pagamento (conto definitivo). Include ENASARCO (RT04), esclude i
  contributi previdenziali puri (TC senza codice ritenuta), che non vanno in CU.
  Niente doppio conteggio con il conto di transizione (appoggio).
- **Imponibile**: recuperato dalle righe-base della stessa scrittura cash basis,
  collegate alla ritenuta tramite `account_move_line_account_tax_rel`.
- `imponibile` e `ritenuta` sono esposti come **importi positivi**; la colonna/filtro
  **Direzione** distingue *subite* (vendite) da *operate* (acquisti).

## Dipendenze

`account`, `l10n_it_edi_withholding`.
