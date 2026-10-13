"""Захист критичного циклу: кеш реєстру карток, бюджет часу й RSS-ліміт аналітики методик, scout не блокує цикл подій."""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name); ok = ok and bool(cond)

from office2 import method_evidence as ME
t = time.perf_counter(); a = ME.load_rules(); t1 = time.perf_counter() - t
t = time.perf_counter()
for _ in range(200): b = ME.load_rules()
t2 = (time.perf_counter() - t) / 200
check("реєстр: 82 картки", len(a) == 82 and len(b) == 82)
check("реєстр: кеш (повторний виклик у 5+ разів швидший)", t2 * 5 < t1)
b[0]["rule_id"] = "MUTATED"
check("реєстр: копія, кеш не псується викликачем", ME.load_rules()[0]["rule_id"] != "MUTATED")

from office2 import engine as EN
os.environ["OFFICE2_METHOD_BUDGET_MS"] = "100"; os.environ["OFFICE2_METHOD_RSS_MB"] = "0"
now = time.time()
check("бюджет: перший символ дозволено", EN.method_block_allowed(now))
EN._METHOD_BUDGET["spent"] = 0.2
check("бюджет: після вичерпання пропуск", not EN.method_block_allowed(now))
check("бюджет: новий цикл скидає", EN.method_block_allowed(now + 1))
os.environ["OFFICE2_METHOD_BUDGET_MS"] = "100000"; os.environ["OFFICE2_METHOD_RSS_MB"] = "1"
check("RSS ≥ ліміту → блок вимкнено (автовідкат)", not EN.method_block_allowed(now + 2))
os.environ["OFFICE2_METHOD_RSS_MB"] = "0"

src = open(os.path.join(os.path.dirname(__file__), "..", "office_relay_wizard.py"), encoding="utf-8").read()
seg = src[src.index("for rsym in deep_syms:"): src.index("for rsym in deep_syms:") + 9000]
check("scout: свічки Binance через asyncio.to_thread", "await asyncio.to_thread(_scout_fetch)" in seg and not re.search(r"^\s+rd1 = fetch_candles", seg, re.M))
check("scout: lev_cycle у потоці", "await asyncio.to_thread(_scout_lev)" in seg)
check("scout: fetch_atr_context у потоці", "asyncio.to_thread(fetch_atr_context" in seg)
sys.exit(0 if ok else 1)
