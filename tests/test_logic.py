import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import macro_dashboard as m  # noqa: E402

IND = {i["id"]: i for i in m.INDICATORS}


def test_signal_symmetric():
    assert m.signal(2.5, IND["retail"]) == "green"
    assert m.signal(1.0, IND["retail"]) == "yellow"
    assert m.signal(-0.1, IND["retail"]) == "red"
    # delinquencies: lower is better
    assert m.signal(-0.07, IND["delinq"]) == "green"
    assert m.signal(0.05, IND["delinq"]) == "yellow"
    assert m.signal(0.2, IND["delinq"]) == "red"
    assert m.signal(None, IND["ceo"]) == "na"


def test_yoy_and_real():
    s = [(f"2025-{i:02d}-01", 100.0) for i in range(1, 13)] + [("2026-01-01", 106.0)]
    y = m.yoy(s)
    assert y == [("2026-01-01", 6.000000000000005)] or abs(y[0][1] - 6.0) < 1e-9
    r = m.real_growth(y, {"2026-01-01": 3.4})
    assert abs(r[0][1] - (1.06 / 1.034 - 1) * 100) < 1e-9


def test_annualized():
    s = [(str(i), 100.0) for i in range(13)] + [("13", 101.0)]
    a = m.annualized(s, 13)
    assert abs(a[0][1] - ((1.01 ** 4) - 1) * 100) < 1e-9


def test_stale_and_diff():
    today = dt.date(2026, 10, 14)
    raw = {"loans": {"value": 6.0, "data_date": "2026-08-01", "spark": []}}
    snap = m.make_snapshot(raw, today)
    assert snap["indicators"]["loans"]["stale"] is True       # settimanale vecchio di 74 giorni
    assert snap["indicators"]["retail"]["signal"] == "na"     # mancante -> n.d., mai stimato
    prev = {"indicators": {"loans": {"signal": "yellow", "data_date": "2026-07-01", "value": 4}}}
    cur = {"indicators": {"loans": {"signal": "green", "data_date": "2026-08-01", "value": 6}}}
    assert "da Giallo a Verde" in m.diff_snapshots(prev, cur)[0]


def test_regime():
    assert m.regime({"green": 5, "yellow": 1, "red": 0, "na": 0})[0] == "Espansione"
    assert m.regime({"green": 1, "yellow": 2, "red": 3, "na": 0})[0] == "Rallentamento"
