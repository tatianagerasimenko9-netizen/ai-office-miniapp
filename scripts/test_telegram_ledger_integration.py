#!/usr/bin/env python3
"""Offline source regression for the opt-in Telegram delivery path.

No Telegram, production DB, credentials, or network access.
"""
import ast
from pathlib import Path

root = Path(__file__).resolve().parent.parent
source = (root / "office_relay_wizard.py").read_text(encoding="utf-8")
tree = ast.parse(source)
assert 'OFFICE_TG_PERSISTENT_DEDUP' in source
assert 'reserve_delivery(db_path, dedup_key, stable=ledger_stable)' in source
assert 'ledger_sender_task.cancel()' in source
assert 'delivered=bool(delivered_id), stable=ledger_stable' in source
assert 'if ledger_token and delivered_id and not ledger_committed:' in source
assert 'return None' in source
assert 'finish_trade_telegram(key=dedup_key, delivered=False)' in source
assert 'await ledger_heartbeat' in source
assert 'send_attempted = True' in source
assert 'send_attempted and not delivered_id' in source
assert 'photo outcome ambiguous' in source
assert 'mark_delivery_uncertain(db_path, dedup_key, ledger_token)' in source
assert any(isinstance(node, ast.AsyncFunctionDef) and node.name == "_renew_telegram_lease"
           for node in ast.walk(tree))
print("OK Telegram opt-in integration source guards (offline)")
