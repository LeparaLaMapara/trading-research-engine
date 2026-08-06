"""Storage: hash determinism and snapshot manifest integrity (§5 reproducibility)."""
import pandas as pd

from telemetry.store import Store, content_hash


def _row(ts, symbol="EURUSD", spread=0.8):
    return {
        "ts_utc": ts, "ts_sast": "x", "dow_sast": 0, "hour_sast": 0, "hour_of_week": 0,
        "symbol": symbol, "bid_raw": 100, "ask_raw": 108, "digits": 5, "pip_position": 4,
        "bid": 0.001, "ask": 0.00108, "spread_price": 0.00008, "spread_pips": spread,
        "side": "bid",
    }


def test_content_hash_is_deterministic():
    df = pd.DataFrame([_row(2.0), _row(1.0, "USDJPY")])
    # Row order must not matter — hash is over the SORTED rows.
    df_shuffled = df.iloc[::-1].reset_index(drop=True)
    assert content_hash(df) == content_hash(df_shuffled)


def test_content_hash_changes_with_data():
    a = pd.DataFrame([_row(1.0, spread=0.8)])
    b = pd.DataFrame([_row(1.0, spread=0.9)])
    assert content_hash(a) != content_hash(b)


def test_snapshot_records_matching_manifest(tmp_path):
    db = str(tmp_path / "t.db")
    st = Store(db)
    for i in range(3):
        st.insert_tick(_row(float(i)))
    manifest = st.snapshot(str(tmp_path / "snaps"))
    assert manifest is not None
    assert manifest["rows"] == 3
    # The manifest hash equals a fresh content hash of the stored ticks.
    df = pd.read_sql_query("SELECT * FROM ticks", st.conn)
    assert manifest["sha256"] == content_hash(df)
    st.close()
