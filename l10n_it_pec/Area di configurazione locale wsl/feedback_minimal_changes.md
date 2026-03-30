---
name: Feedback - Solo modifiche richieste
description: L'utente richiede rigorosamente solo le modifiche esplicitamente chieste, nessuna modifica extra o refactoring non richiesto
type: feedback
---

Fare SOLO le modifiche esplicitamente richieste dall'utente. Non toccare file che non sono strettamente necessari per la modifica richiesta.

**Why:** L'utente ha corretto piu volte questo comportamento durante lo sviluppo del modulo l10n_it_pec. In un'occasione ho modificato wizard, bottoni, security rules e manifest quando era richiesto solo di correggere la gestione degli stati nell'invio fatture. L'utente ha dovuto chiedere 3 volte di limitare le modifiche.

**How to apply:** Prima di ogni modifica, chiedersi: "l'utente ha chiesto esplicitamente questo?" Se no, non farlo. Indicare sempre quali file sono stati modificati alla fine. Non aggiungere refactoring, miglioramenti, cleanup o feature non richieste.
