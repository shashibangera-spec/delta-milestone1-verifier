from datetime import date, timedelta
import pytest
from amt_engine.v17_pipeline import PipelineError, _existing, _records, main

def test_backfill_date_range_is_inclusive_and_ordered():
    first, last = date(2026, 11, 20), date(2026, 11, 22)
    assert [first + timedelta(days=i) for i in range((last-first).days+1)] == [
        date(2026, 11, 20), date(2026, 11, 21), date(2026, 11, 22)
    ]

def test_source_query_builder_rejects_missing_slots():
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def execute(self,*args): pass
        def fetchall(self): return []
    class Conn:
        def cursor(self): return Cursor()
    with pytest.raises(PipelineError, match="expected 48 ordered candle OPEN slots"):
        _records(Conn(), date(2026,11,21), "PRICE", "BTCUSD")

def test_existing_profile_without_fingerprint_is_not_silently_skipped():
    class Cursor:
        def __init__(self): self.calls=0
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def execute(self,*args): self.calls+=1
        def fetchall(self):
            return [{"profile_id":"x","profile_status":"COMPLETE","is_complete":True,
                     "bundle_sha256":None,"persisted_sha256":None}]
    class Conn:
        def cursor(self): return Cursor()
    with pytest.raises(PipelineError, match="manual reconciliation"):
        _existing(Conn(), date(2026,11,21))
