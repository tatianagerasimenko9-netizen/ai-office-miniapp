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
# A return inside finally suppresses CancelledError and can falsely acknowledge sends.
send_proactive = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.AsyncFunctionDef) and node.name == "send_proactive")
assert not any(isinstance(n, ast.Return) for part in send_proactive.body
               if isinstance(part, ast.Try) for final in part.finalbody
               for n in ast.walk(final)), "finally must not return"
assert 'return delivered_id if ledger_committed else None' in source
assert any(isinstance(node, ast.AsyncFunctionDef) and node.name == "_renew_telegram_lease"
           for node in ast.walk(tree))
print("OK Telegram opt-in integration source guards (offline)")
