import unittest
from datetime import date, datetime, timezone
from scripts.research_v15_walkforward_audit import split_for_day, split_end_exclusive, match_controls, summarize

UTC=timezone.utc

class WalkForwardAuditTests(unittest.TestCase):
    def test_split_boundaries(self):
        self.assertIsNone(split_for_day(date(2026,5,21)))
        self.assertEqual(split_for_day(date(2026,5,22)),"IN_SAMPLE")
        self.assertEqual(split_for_day(date(2026,8,31)),"IN_SAMPLE")
        self.assertEqual(split_for_day(date(2026,9,1)),"BLIND_OUT_OF_SAMPLE")
        self.assertEqual(split_for_day(date(2026,11,26)),"BLIND_OUT_OF_SAMPLE")
        self.assertIsNone(split_for_day(date(2026,11,27)))
        self.assertEqual(split_end_exclusive("IN_SAMPLE"),datetime(2026,9,1,tzinfo=UTC))

    def test_match_one_to_one_and_within_split(self):
        events=[
          {"entry_time":datetime(2026,6,1,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":250.},
          {"entry_time":datetime(2026,6,2,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":300.}]
        controls=[
          {"entry_time":datetime(2026,6,3,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":251.},
          {"entry_time":datetime(2026,6,4,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":299.},
          {"entry_time":datetime(2026,6,5,tzinfo=UTC),"split":"BLIND_OUT_OF_SAMPLE","sub_session":"Asia","risk_points":250.}]
        pairs,unmatched=match_controls(events,controls)
        self.assertEqual(len(pairs),2); self.assertFalse(unmatched)
        self.assertEqual([p["control"]["risk_points"] for p in pairs],[251.,299.])
        self.assertEqual(len({p["control"]["entry_time"] for p in pairs}),2)

    def test_earliest_timestamp_breaks_width_tie(self):
        event=[{"entry_time":datetime(2026,6,1,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Europe","risk_points":250.}]
        controls=[
          {"entry_time":datetime(2026,6,4,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Europe","risk_points":249.},
          {"entry_time":datetime(2026,6,3,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Europe","risk_points":251.}]
        pairs,_=match_controls(event,controls)
        self.assertEqual(pairs[0]["control"]["entry_time"],datetime(2026,6,3,tzinfo=UTC))

    def test_empty_metrics(self):
        self.assertEqual(summarize([])["trades"],0)

if __name__=="__main__": unittest.main()
