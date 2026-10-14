# NOTE — scelte di metodo

Ogni scelta con il suo motivo. Se una fonte cambia o smette di aggiornarsi, si aggiorna la riga esistente.

## Fonti

| Indicatore | Fonte | Automatico? | Motivo |
|---|---|---|---|
| Retail Sales | FRED `RSAFS` (Census), deflazionato con `CPIAUCSL` | Sì | Fonte ufficiale, API gratuita. Il +5% nominale di partenza con inflazione al 3-4% è meno forte di come appare, quindi il segnale usa la crescita reale. |
| ISM Services New Orders | `data/manual.json` | No | ISM non è su FRED dal 2016 e i dati sono sotto licenza. Un numero al mese, inserimento in 30 secondi. |
| Bank Loan Growth | FRED `TOTLL` (Fed H.8), crescita annualizzata a 13 settimane | Sì | È l'unico dei 6 davvero settimanale. Limite: non è corretto per le discontinuità che la Fed applica nella Tabella 1 del comunicato H.8. |
| Delinquencies | FRED `DRALACBS` (Fed), variazione annua in punti % | Sì | Conta la direzione, non il livello. La variazione annua elimina la stagionalità residua. |
| Ristoranti | FRED `RSFSDP` (Census, ristoranti e bar), crescita reale | Sì | OpenTable pubblica i dati solo in una pagina dinamica, senza file scaricabile in modo automatico (verificato il 14/10/2026). Il proxy Census è mensile e copre tutto il settore. |
| CEO Confidence | `data/manual.json` | No | Conference Board: comunicato trimestrale, serie storica a pagamento. |

## Soglie (simmetriche, verde / giallo / rosso)

| Indicatore | Verde | Giallo | Rosso | Motivo |
|---|---|---|---|---|
| Retail Sales reale | ≥ +2% | 0 / +2% | < 0% | +2% reale è circa il passo di un consumatore in salute. Sotto zero il consumo reale si contrae. |
| ISM New Orders | ≥ 55 | 50 / 55 | < 50 | 50 è lo spartiacque espansione/contrazione. 55 separa la crescita solida da quella debole. |
| Prestiti 3 mesi annualizzati | ≥ 5% | 2 / 5% | < 2% | Crescita annua H.8: 2,9% nel 2024, 5,4% nel 2025. Sopra il 5% il credito corre più della media recente. |
| Insolvenze, var. annua | ≤ −0,05 pp | −0,05 / +0,10 | > +0,10 pp | Asimmetria voluta: un rialzo delle insolvenze è un segnale di rischio più importante di un calo. |
| Ristoranti reale | ≥ +1,5% | 0 / +1,5% | < 0% | Spesa discrezionale: soglia un po' più bassa delle vendite totali. |
| CEO Confidence | ≥ 60 | 50 / 60 | < 50 | Sopra 50 prevalgono le risposte positive. 60 è un livello di vero ottimismo. La tesi "ai massimi" non si può misurare senza la serie storica completa. |

## Regime (regola meccanica)

- Rallentamento: almeno 3 rossi.
- Espansione: almeno 5 verdi.
- Espansione con crepe: almeno 3 verdi e al massimo 1 rosso.
- Misto: tutto il resto.

## Dati vecchi

Un indicatore è segnalato come vecchio se la data del dato supera: 21 giorni (settimanale), 80 giorni (mensile), 140 giorni (CEO, trimestrale), 250 giorni (insolvenze, escono circa 5 mesi dopo il trimestre).

## Snapshot iniziale 14/10/2026

`data/seed_2026-10-14.json` contiene solo valori controllati contro le fonti: Census MARTS 16/09/2026, comunicato ISM 05/10/2026, Fed H.8 09/10/2026, Fed charge-off 25/08/2026, Conference Board 06/08/2026. Per i prestiti usa la crescita ufficiale H.8 corretta per le discontinuità, non il calcolo da TOTLL.
