"""Read-only B&R paper evidence report. Requires DATABASE_URL environment variable."""
import json
import os
from office_br.analyst_evidence import evaluate_database

if __name__ == "__main__":
    db = os.environ["DATABASE_URL"]
    print(json.dumps(evaluate_database(db), ensure_ascii=False, sort_keys=True))
