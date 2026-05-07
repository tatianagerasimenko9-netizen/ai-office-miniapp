import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from office_bridge import init_office_db

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL не задано")
    sys.exit(1)

print(f"Підключаємось до: {db_url[:30]}...")
init_office_db(db_url)
print("✓ Таблиці створені успішно")
