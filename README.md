# Macro Pulse USA

Dashboard con i 6 numeri macro USA da guardare ogni settimana. Si aggiorna da sola ogni lunedì mattina con GitHub Actions e si pubblica su GitHub Pages.

## Messa in funzione (circa 10 minuti, una volta sola)

1. Chiedi una chiave API gratuita a FRED: https://fred.stlouisfed.org/docs/api/api_key.html
2. Crea un repository GitHub e carica questi file.
3. Nel repository: Settings → Secrets and variables → Actions → New repository secret. Nome `FRED_API_KEY`, valore la tua chiave.
4. Settings → Pages → Source "Deploy from a branch", branch `main`, cartella `/docs`.
5. Actions → "Aggiorna dashboard macro" → Run workflow. Dopo un minuto la pagina è online.

## Manutenzione

- Ogni mese, dopo il report ISM Services: aggiungi una riga in `data/manual.json`.
- Ogni trimestre, dopo il comunicato Conference Board: aggiungi una riga CEO Confidence.
- Se non lo fai, la scheda si colora con l'avviso "Dato vecchio". Il numero non viene mai stimato.

## Prova in locale

```
pip install pytest && pytest -q tests
FRED_API_KEY=la_tua_chiave python macro_dashboard.py
```

Scelte di fonti e soglie: vedi `NOTE.md`.
