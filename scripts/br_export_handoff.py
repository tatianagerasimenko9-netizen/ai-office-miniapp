"""Read-only: вивантажує унікальні плани B&R у docs/handoff/br-profitability/data/br_plans.psv. Потрібен DATABASE_URL."""
import os, pathlib
import psycopg2
sql = (pathlib.Path(__file__).parents[1] / "docs/handoff/br-profitability/export_br_data.sql").read_text()
out = pathlib.Path(__file__).parents[1] / "docs/handoff/br-profitability/data"
out.mkdir(exist_ok=True)
with psycopg2.connect(os.environ["DATABASE_URL"]) as c, c.cursor() as cur:
    cur.execute("set transaction read only"); cur.execute(sql)
    (out / "br_plans.psv").write_text("seq|sym|dir|created_ts|entry|sl|targets|events\n" + (cur.fetchone()[0] or "") + "\n")
print("ok")
