"""Dashboard macro USA: 6 indicatori settimanali.

Uso:
  python macro_dashboard.py                 # live: FRED API (serve FRED_API_KEY) + data/manual.json
  python macro_dashboard.py --seed FILE     # costruisce la pagina da uno snapshot gia' verificato

Scrive: data/latest.json, data/history.json, docs/index.html
Nessun valore viene stimato o inventato: se una serie manca, l'indicatore resta "n.d.".
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

# ---------------------------------------------------------------- configurazione
# Soglie simmetriche: verde / giallo / rosso. "higher_is_better" decide il verso.
INDICATORS = [
    {
        "id": "retail",
        "name": "Retail Sales",
        "metric": "Crescita annua reale",
        "unit": "%",
        "freq": "mensile",
        "stale_days": 80,
        "green": 2.0, "red": 0.0, "higher_is_better": True,
        "rule": "Verde ≥ +2% reale · Giallo 0/+2% · Rosso < 0%",
        "source": "Census via FRED (RSAFS), deflazionato con CPI (CPIAUCSL)",
        "url": "https://fred.stlouisfed.org/series/RSAFS",
    },
    {
        "id": "ism_no",
        "name": "ISM Services New Orders",
        "metric": "Indice di diffusione",
        "unit": "",
        "freq": "mensile",
        "stale_days": 80,
        "green": 55.0, "red": 50.0, "higher_is_better": True,
        "rule": "Verde ≥ 55 · Giallo 50/55 · Rosso < 50 (contrazione)",
        "source": "ISM Report On Business (inserimento manuale, licenza ISM)",
        "url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/services/",
    },
    {
        "id": "loans",
        "name": "Bank Loan Growth",
        "metric": "Crescita annualizzata 3 mesi",
        "unit": "%",
        "freq": "settimanale",
        "stale_days": 21,
        "green": 5.0, "red": 2.0, "higher_is_better": True,
        "rule": "Verde ≥ 5% · Giallo 2/5% · Rosso < 2%",
        "source": "Fed H.8 via FRED (TOTLL, prestiti e leasing totali)",
        "url": "https://www.federalreserve.gov/releases/h8/current/",
    },
    {
        "id": "delinq",
        "name": "Delinquencies",
        "metric": "Variazione annua del tasso (punti %)",
        "unit": " pp",
        "freq": "trimestrale",
        "stale_days": 250,
        "green": -0.05, "red": 0.10, "higher_is_better": False,
        "rule": "Verde ≤ −0,05 pp · Giallo −0,05/+0,10 · Rosso > +0,10 pp",
        "source": "Fed, tasso di insolvenza su tutti i prestiti, via FRED (DRALACBS)",
        "url": "https://www.federalreserve.gov/releases/chargeoff/delallsa.htm",
    },
    {
        "id": "dining",
        "name": "Ristoranti (proxy OpenTable)",
        "metric": "Crescita annua reale vendite",
        "unit": "%",
        "freq": "mensile",
        "stale_days": 80,
        "green": 1.5, "red": 0.0, "higher_is_better": True,
        "rule": "Verde ≥ +1,5% reale · Giallo 0/+1,5% · Rosso < 0%",
        "source": "Census, ristoranti e bar, via FRED (RSFSDP), deflazionato con CPI",
        "url": "https://fred.stlouisfed.org/series/RSFSDP",
    },
    {
        "id": "ceo",
        "name": "CEO Confidence",
        "metric": "Indice Conference Board",
        "unit": "",
        "freq": "trimestrale",
        "stale_days": 140,
        "green": 60.0, "red": 50.0, "higher_is_better": True,
        "rule": "Verde ≥ 60 · Giallo 50/60 · Rosso < 50 (pessimismo prevalente)",
        "source": "The Conference Board (inserimento manuale)",
        "url": "https://www.conference-board.org/topics/CEO-confidence",
    },
]

SIGNAL_LABEL = {"green": "Verde", "yellow": "Giallo", "red": "Rosso", "na": "n.d."}


# ---------------------------------------------------------------- calcoli puri
def signal(value: float | None, ind: dict) -> str:
    if value is None:
        return "na"
    g, r = ind["green"], ind["red"]
    if ind["higher_is_better"]:
        if value >= g:
            return "green"
        if value < r:
            return "red"
        return "yellow"
    if value <= g:
        return "green"
    if value > r:
        return "red"
    return "yellow"


def yoy(series: list[tuple[str, float]], periods: int = 12) -> list[tuple[str, float]]:
    """Variazione % su `periods` osservazioni prima (12 = annua per serie mensili)."""
    out = []
    for i in range(periods, len(series)):
        d, v = series[i]
        _, v0 = series[i - periods]
        if v0:
            out.append((d, (v / v0 - 1) * 100))
    return out


def real_growth(nominal: list[tuple[str, float]], cpi_yoy: dict[str, float]) -> list[tuple[str, float]]:
    """Crescita reale esatta: (1+n)/(1+p)-1. Usa solo mesi con CPI disponibile."""
    out = []
    for d, n in nominal:
        if d in cpi_yoy:
            out.append((d, ((1 + n / 100) / (1 + cpi_yoy[d] / 100) - 1) * 100))
    return out


def annualized(series: list[tuple[str, float]], weeks: int = 13) -> list[tuple[str, float]]:
    """Crescita annualizzata su `weeks` settimane per serie settimanali."""
    out = []
    for i in range(weeks, len(series)):
        d, v = series[i]
        _, v0 = series[i - weeks]
        if v0:
            out.append((d, ((v / v0) ** (52 / weeks) - 1) * 100))
    return out


def change(series: list[tuple[str, float]], periods: int) -> list[tuple[str, float]]:
    out = []
    for i in range(periods, len(series)):
        out.append((series[i][0], series[i][1] - series[i - periods][1]))
    return out


def age_days(data_date: str, today: dt.date) -> int:
    return (today - dt.date.fromisoformat(data_date)).days


def trend(series: list[tuple[str, float]]) -> str:
    if len(series) < 2:
        return "flat"
    diff = series[-1][1] - series[-2][1]
    if abs(diff) < 1e-9:
        return "flat"
    return "up" if diff > 0 else "down"


def diff_snapshots(prev: dict | None, cur: dict) -> list[str]:
    """Cosa e' cambiato rispetto all'ultimo aggiornamento salvato."""
    if not prev:
        return ["Primo aggiornamento: nessun confronto disponibile con la settimana precedente."]
    notes = []
    for ind in INDICATORS:
        a = prev["indicators"].get(ind["id"])
        b = cur["indicators"].get(ind["id"])
        if not a or not b:
            continue
        if a["signal"] != b["signal"]:
            notes.append(f"{ind['name']}: da {SIGNAL_LABEL[a['signal']]} a {SIGNAL_LABEL[b['signal']]}.")
        elif a.get("data_date") != b.get("data_date") and b.get("value") is not None:
            notes.append(f"{ind['name']}: nuovo dato ({b['data_date']}), segnale invariato.")
    return notes or ["Nessun dato nuovo e nessun cambio di segnale."]


def regime(counts: dict) -> tuple[str, str]:
    """Lettura meccanica: conta i segnali, non interpreta."""
    g, r = counts["green"], counts["red"]
    if r >= 3:
        return "Rallentamento", "Almeno 3 indicatori in rosso."
    if g >= 5:
        return "Espansione", "Almeno 5 indicatori su 6 in verde."
    if g >= 3 and r <= 1:
        return "Espansione con crepe", "Maggioranza verde, ma non piena."
    return "Misto", "Segnali discordanti: nessuna maggioranza chiara."


# ---------------------------------------------------------------- dati live
def fred(series_id: str, key: str, start: str) -> list[tuple[str, float]]:
    q = urllib.parse.urlencode({
        "series_id": series_id, "api_key": key, "file_type": "json", "observation_start": start,
    })
    with urllib.request.urlopen(f"https://api.stlouisfed.org/fred/series/observations?{q}", timeout=30) as r:
        obs = json.load(r)["observations"]
    return [(o["date"], float(o["value"])) for o in obs if o["value"] not in (".", "")]


def build_live(key: str) -> dict:
    start5 = (dt.date.today() - dt.timedelta(days=5 * 365)).isoformat()
    cpi = dict(yoy(fred("CPIAUCSL", key, start5)))
    manual = json.loads((DATA / "manual.json").read_text())
    out = {}

    def pack(series, extra=None, spark_n=12):
        if not series:
            return {"value": None, "data_date": None, "spark": [], "extra": extra or {}}
        return {
            "value": round(series[-1][1], 2),
            "prev": round(series[-2][1], 2) if len(series) > 1 else None,
            "data_date": series[-1][0],
            "spark": [[d, round(v, 2)] for d, v in series[-spark_n:]],
            "extra": extra or {},
        }

    rs_nom = yoy(fred("RSAFS", key, start5))
    out["retail"] = pack(real_growth(rs_nom, cpi), {"Nominale": f"{rs_nom[-1][1]:+.1f}%" if rs_nom else "n.d."})

    tl = fred("TOTLL", key, start5)
    loans = annualized(tl, 13)
    out["loans"] = pack(loans, {"Livello": f"${tl[-1][1] / 1000:,.0f} mld" if tl else "n.d.",
                                "Metodo": "13 settimane, non corretto per discontinuita'"}, spark_n=26)

    dq = fred("DRALACBS", key, start5)
    dq_chg = change(dq, 4)
    out["delinq"] = pack(dq_chg, {"Livello": f"{dq[-1][1]:.2f}%" if dq else "n.d."}, spark_n=8)

    fs_nom = yoy(fred("RSFSDP", key, start5))
    out["dining"] = pack(real_growth(fs_nom, cpi), {"Nominale": f"{fs_nom[-1][1]:+.1f}%" if fs_nom else "n.d."})

    ism = [(r["date"], float(r["value"])) for r in manual.get("ism_services_new_orders", [])]
    out["ism_no"] = pack(ism, {"Fonte": "data/manual.json"})
    ceo = [(r["date"], float(r["value"])) for r in manual.get("ceo_confidence", [])]
    out["ceo"] = pack(ceo, {"Fonte": "data/manual.json"}, spark_n=8)
    return out


# ---------------------------------------------------------------- snapshot
def make_snapshot(raw: dict, today: dt.date) -> dict:
    inds = {}
    for ind in INDICATORS:
        r = raw.get(ind["id"], {})
        v = r.get("value")
        dd = r.get("data_date")
        age = age_days(dd, today) if dd else None
        inds[ind["id"]] = {
            "value": v,
            "prev": r.get("prev"),
            "data_date": dd,
            "age_days": age,
            "stale": age is None or age > ind["stale_days"],
            "signal": signal(v, ind),
            "trend": trend([tuple(p) for p in r.get("spark", [])]),
            "spark": r.get("spark", []),
            "extra": r.get("extra", {}),
            "note": r.get("note"),
        }
    counts = {k: sum(1 for i in inds.values() if i["signal"] == k) for k in ("green", "yellow", "red", "na")}
    return {"run_date": today.isoformat(), "indicators": inds, "counts": counts}


# ---------------------------------------------------------------- HTML
def sparkline(points: list, higher_is_better: bool) -> str:
    if len(points) < 2:
        return '<div class="spark-empty">Storico non ancora disponibile</div>'
    vals = [p[1] for p in points]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    w, h, pad = 220, 48, 4
    xs = [pad + i * (w - 2 * pad) / (len(vals) - 1) for i in range(len(vals))]
    ys = [h - pad - (v - lo) / (hi - lo) * (h - 2 * pad) for v in vals]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{h} {line} {xs[-1]:.1f},{h}"
    first, last = points[0][0], points[-1][0]
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
        f'aria-label="Andamento da {first} a {last}">'
        f'<polygon points="{area}" class="spark-area"/>'
        f'<polyline points="{line}" class="spark-line" fill="none"/>'
        f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="3.2" class="spark-dot"/></svg>'
        f'<div class="spark-range"><span>{first[:7]}</span><span>{last[:7]}</span></div>'
    )


def fmt(v, unit: str) -> str:
    if v is None:
        return "n.d."
    if unit.strip() in ("%", "pp"):
        s = f"{v:+.2f}" if unit.strip() == "pp" else f"{v:+.1f}"
    else:
        s = f"{v:.1f}"
    return s.replace(".", ",") + unit


TREND_TXT = {"up": "↑ in salita", "down": "↓ in discesa", "flat": "→ stabile"}

CSS = """
/* Layout: banda di sintesi in alto, poi griglia di 6 schede uguali (3 / 2 / 1 colonne) */
:root{
  --bg:#f3f5f7; --surface:#ffffff; --ink:#14202b; --muted:#5b6b78; --line:#d9e0e6;
  --accent:#1f4e79;
  --ok:#1d7a4a; --ok-bg:#e3f3ea; --warn:#9a6a00; --warn-bg:#fbf0d6; --bad:#b3261e; --bad-bg:#fbe4e2;
  --na:#6b7680; --na-bg:#eceff2;
  --f-display:"Archivo", "Helvetica Neue", Arial, sans-serif;
  --f-body:"Source Sans 3", "Segoe UI", Arial, sans-serif;
  --f-data:"JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0f161c; --surface:#16202a; --ink:#e6edf3; --muted:#93a3b1; --line:#26333f; --accent:#7fb3e6;
  --ok:#5fd394; --ok-bg:#12301f; --warn:#f0c255; --warn-bg:#33280c; --bad:#ff8a80; --bad-bg:#3a1714;
  --na:#9aa6b1; --na-bg:#202b35; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0f161c; --surface:#16202a; --ink:#e6edf3; --muted:#93a3b1; --line:#26333f; --accent:#7fb3e6;
  --ok:#5fd394; --ok-bg:#12301f; --warn:#f0c255; --warn-bg:#33280c; --bad:#ff8a80; --bad-bg:#3a1714;
  --na:#9aa6b1; --na-bg:#202b35; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:15px;line-height:1.5;
  padding-left:max(16px, env(safe-area-inset-left, 0px));padding-right:max(16px, env(safe-area-inset-right, 0px));
  padding-block:24px 40px}
.wrap{max-width:1180px;margin:0 auto;display:grid;gap:20px}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px}
h1{font-family:var(--f-display);font-weight:800;font-size:clamp(1.6rem,3.2vw,2.3rem);letter-spacing:-0.01em;margin:0;text-wrap:balance}
.eyebrow{font-family:var(--f-data);font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.meta{font-family:var(--f-data);font-size:.8rem;color:var(--muted);text-align:right}
.summary{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:20px;
  display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:24px}
.regime{font-family:var(--f-display);font-weight:800;font-size:1.7rem;margin:4px 0 2px}
.regime-why{color:var(--muted);margin:0}
.tally{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
.tally span{font-family:var(--f-data);font-size:.85rem;padding:4px 10px;border-radius:999px;font-variant-numeric:tabular-nums}
.changes h2,.caveats h2{font-family:var(--f-display);font-size:.95rem;margin:0 0 8px}
.changes ul,.caveats ul{margin:0;padding-left:18px;display:grid;gap:4px}
.s-green{color:var(--ok);background:var(--ok-bg)} .s-yellow{color:var(--warn);background:var(--warn-bg)}
.s-red{color:var(--bad);background:var(--bad-bg)} .s-na{color:var(--na);background:var(--na-bg)}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px;display:grid;gap:10px;
  align-content:start;border-top-width:4px}
.card.b-green{border-top-color:var(--ok)} .card.b-yellow{border-top-color:var(--warn)}
.card.b-red{border-top-color:var(--bad)} .card.b-na{border-top-color:var(--na)}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.card h3{font-family:var(--f-display);font-size:1.05rem;margin:0;text-wrap:balance}
.metric{color:var(--muted);font-size:.85rem}
.pill{font-family:var(--f-data);font-size:.75rem;font-weight:700;padding:3px 9px;border-radius:999px;white-space:nowrap}
.value{font-family:var(--f-data);font-size:2rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}
.trend{font-family:var(--f-data);font-size:.82rem;color:var(--muted)}
.spark{width:100%;height:48px;display:block}
.spark-line{stroke:var(--accent);stroke-width:2;vector-effect:non-scaling-stroke}
.spark-area{fill:var(--accent);opacity:.12}
.spark-dot{fill:var(--accent)}
.spark-range{display:flex;justify-content:space-between;font-family:var(--f-data);font-size:.7rem;color:var(--muted)}
.spark-empty{font-size:.8rem;color:var(--muted);border:1px dashed var(--line);border-radius:6px;padding:14px;text-align:center}
dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:3px 12px;margin:0;font-size:.85rem}
dt{color:var(--muted)} dd{margin:0;font-family:var(--f-data);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.stale{font-family:var(--f-data);font-size:.75rem;color:var(--bad);background:var(--bad-bg);padding:4px 8px;border-radius:6px}
.fresh{font-family:var(--f-data);font-size:.75rem;color:var(--muted)}
.rule{font-size:.78rem;color:var(--muted);border-top:1px solid var(--line);padding-top:8px}
.note{font-size:.82rem;background:var(--na-bg);border-radius:6px;padding:8px 10px}
a{color:var(--accent)} a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.caveats{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px;font-size:.9rem}
footer{font-size:.8rem;color:var(--muted)}
@media (max-width:980px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:640px){.grid,.summary{grid-template-columns:minmax(0,1fr)}.meta{text-align:left}}
"""


def render(snap: dict, changes: list[str], caveats: list[str], mode_note: str) -> str:
    counts = snap["counts"]
    reg, why = regime(counts)
    cards = []
    for ind in INDICATORS:
        s = snap["indicators"][ind["id"]]
        extras = "".join(f"<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>" for k, v in s["extra"].items())
        age = f"{s['age_days']} giorni fa" if s["age_days"] is not None else "n.d."
        fresh = (f'<div class="stale">Dato vecchio: ultimo del {s["data_date"]} ({age})</div>' if s["stale"]
                 else f'<div class="fresh">Ultimo dato: {s["data_date"]} · {age}</div>')
        note = f'<div class="note">{html.escape(s["note"])}</div>' if s.get("note") else ""
        cards.append(f"""
<article class="card b-{s['signal']}">
  <div class="card-head">
    <div><h3>{html.escape(ind['name'])}</h3><div class="metric">{html.escape(ind['metric'])}</div></div>
    <span class="pill s-{s['signal']}">{SIGNAL_LABEL[s['signal']]}</span>
  </div>
  <div class="value">{fmt(s['value'], ind['unit'])}</div>
  <div class="trend">{TREND_TXT[s['trend']]} rispetto al dato precedente</div>
  {sparkline(s['spark'], ind['higher_is_better'])}
  <dl><dt>Frequenza</dt><dd>{ind['freq']}</dd>{extras}</dl>
  {fresh}{note}
  <div class="rule">{html.escape(ind['rule'])}<br>Fonte: <a href="{ind['url']}" target="_blank" rel="noopener">{html.escape(ind['source'])}</a></div>
</article>""")
    tally = "".join(
        f'<span class="s-{k}">{SIGNAL_LABEL[k]} {counts[k]}</span>' for k in ("green", "yellow", "red", "na") if counts[k] or k != "na"
    )
    ch = "".join(f"<li>{html.escape(c)}</li>" for c in changes)
    cv = "".join(f"<li>{html.escape(c)}</li>" for c in caveats)
    return f"""<title>Macro Pulse USA</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=JetBrains+Mono:wght@400;700&family=Source+Sans+3:wght@400;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <div><div class="eyebrow">6 numeri · lettura settimanale · USA</div><h1>Macro Pulse USA</h1></div>
  <div class="meta">Aggiornato il {snap['run_date']}<br>{html.escape(mode_note)}</div>
</header>
<section class="summary">
  <div>
    <div class="eyebrow">Regime (regola meccanica)</div>
    <div class="regime">{reg}</div>
    <p class="regime-why">{why}</p>
    <div class="tally">{tally}</div>
  </div>
  <div class="changes"><h2>Cosa è cambiato dall'ultimo aggiornamento</h2><ul>{ch}</ul></div>
</section>
<section class="grid">{''.join(cards)}</section>
<section class="caveats"><h2>Cosa il semaforo non vede</h2><ul>{cv}</ul></section>
<footer>Le soglie sono scelte di metodo, non verità di mercato: sono spiegate in NOTE.md. Nessun valore mancante viene stimato.</footer>
</div>"""


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", help="snapshot JSON gia' verificato (salta FRED)")
    ap.add_argument("--today", help="data di riferimento YYYY-MM-DD (test)")
    ap.add_argument("--out", default=str(DOCS / "index.html"))
    ap.add_argument("--fragment", action="store_true", help="senza <html>/<head> (per anteprime Claude)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()

    if a.seed:
        seed = json.loads(Path(a.seed).read_text())
        raw, caveats, mode = seed["indicators"], seed.get("caveats", []), seed.get("mode_note", "Snapshot verificato")
    else:
        key = os.environ.get("FRED_API_KEY")
        if not key:
            print("FRED_API_KEY mancante: aggiungila nei secrets del repository.", file=sys.stderr)
            return 2
        raw = build_live(key)
        caveats = json.loads((DATA / "manual.json").read_text()).get("caveats", [])
        mode = "Aggiornamento automatico (FRED + inserimenti manuali)"

    snap = make_snapshot(raw, today)
    hist_path = DATA / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else []
    prev = next((h for h in reversed(history) if h["run_date"] != snap["run_date"]), None)
    changes = diff_snapshots(prev, snap)

    slim = {"run_date": snap["run_date"], "counts": snap["counts"],
            "indicators": {k: {f: v[f] for f in ("value", "data_date", "signal")} for k, v in snap["indicators"].items()}}
    history = [h for h in history if h["run_date"] != snap["run_date"]] + [slim]
    DATA.mkdir(exist_ok=True)
    hist_path.write_text(json.dumps(history[-104:], indent=1, ensure_ascii=False))
    (DATA / "latest.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    page = render(snap, changes, caveats, mode)
    if not a.fragment:
        head, body = page.split("</style>", 1)
        page = ('<!doctype html>\n<html lang="it">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                f'{head}</style>\n</head>\n<body>{body}\n</body>\n</html>\n')
    Path(a.out).write_text(page, encoding="utf-8")
    print(json.dumps(snap["counts"]), regime(snap["counts"])[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
