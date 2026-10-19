import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.m1_run_production import execute

def test_one_command_read_only():
    def query(db,sql):
        assert db=="test-db" and sql.startswith("SELECT")
        if "FROM br_test_signal" in sql and "FROM br_test_event" not in sql:
            return [("X","ETHUSDT","LONG",0,100,99,
                     '[{"p":101},{"p":102},{"p":103}]',900,"SL")]
        return [("X","ENTRY",900),("X","SL",960)]
    def fetch(symbol,start,end):
        return [{"ts":900,"high":100.1,"low":99.9},
                {"ts":960,"high":100.1,"low":98.9}]
    x=execute("test-db",query=query,fetch=fetch)
    assert x["summary"]["verdicts"]["MATCH"]==1
    assert x["source_signal_count"]==1 and x["source_event_count"]==2
    assert x["db_write_count"]==0

if __name__=="__main__":
    test_one_command_read_only()
    print("OK")
