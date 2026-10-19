import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.m1_export import extract,SIGNAL_COLUMNS,EVENT_COLUMNS

def test_export_selects_read_only():
    queries=[]
    def query(db,sql):
        queries.append(sql)
        assert db=="dummy"
        assert sql.strip().startswith("SELECT")
        if "FROM br_test_signal" in sql and "FROM br_test_event" not in sql:
            return [("S","ETHUSDT","LONG",0,100,99,'[{"p":101},{"p":102},{"p":103}]',900,"SL")]
        return [("S","SL",960)]
    signals,events=extract("dummy",query=query)
    assert len(queries)==2
    assert signals[0]["sig_id"]=="S" and events[0]["level"]=="SL"
    assert set(signals[0])==set(SIGNAL_COLUMNS)
    assert set(events[0])==set(EVENT_COLUMNS)

if __name__=="__main__":
    test_export_selects_read_only()
    print("OK")
