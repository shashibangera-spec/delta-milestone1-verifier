import unittest
from collections import defaultdict
import math

ROW_SIZE=50.0
def profile(candles):
    counts=defaultdict(int)
    for c in candles:
        lo=math.floor(c["low"]/ROW_SIZE); hi=math.floor(c["high"]/ROW_SIZE)
        for k in range(lo,hi+1): counts[k]+=1
    if not counts: return None
    top=max(counts.values()); poc=min(k for k,v in counts.items() if v==top)
    target=math.ceil(sum(counts.values())*.70)
    lo=hi=poc; included=counts[poc]
    while included<target:
        lc=counts.get(lo-1,0); hc=counts.get(hi+1,0)
        if not lc and not hc: break
        if lc>=hc: lo-=1; included+=lc
        else: hi+=1; included+=hc
    return (lo*50,poc*50,(hi+1)*50)
class TPOTests(unittest.TestCase):
    def test_each_bar_counts_each_touched_row_once(self):
        self.assertEqual(profile([{"low":100,"high":200}]),(100,100,250))
    def test_poc_tie_chooses_lower_row(self):
        p=profile([{"low":100,"high":150}])
        self.assertEqual(p[1],100)
    def test_empty(self):
        self.assertIsNone(profile([]))
    def test_70_percent_expansion_tie_goes_lower(self):
        # Three bars hit rows 100 and 150 equally; tie POC lower; VA expands down when adjacent counts tie.
        p=profile([{"low":100,"high":150} for _ in range(3)])
        self.assertEqual(p,(100,100,200))
if __name__=="__main__": unittest.main()
