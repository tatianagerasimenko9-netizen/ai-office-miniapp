#!/usr/bin/env python3
"""docs/methodology/TRACEABILITY.md з docs/sources/evidence.jsonl: один рядок на правило — метод, автор, ТФ, клас доказу, реалізація (код), відповідність, чого НЕ ПІДТВЕРДЖЕНО. Нічого не додає від себе."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = [json.loads(l) for l in (ROOT / "docs" / "sources" / "evidence.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
esc = lambda s: str(s if s is not None else "—").replace("|", "/").replace("\n", " ")  # noqa: E731
out = ["# TRACEABILITY — методики → правила → код → статус", "",
       "Згенеровано з `docs/sources/evidence.jsonl` (`python3 scripts/gen_traceability.py`). Статус береться з реєстру, не з назви методу. «НЕ ПІДТВЕРДЖЕНО» = у наданих матеріалах числа/правила немає.", ""]
st = Counter(r.get("implementation_status") for r in rows)
out.append("Підсумок за статусом реалізації: " + ", ".join(f"{k}: {v}" for k, v in sorted(st.items(), key=lambda x: -x[1])))
out.append("")
for method in sorted({r.get("method") for r in rows}, key=str):
    out += [f"## {method}", "", "| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |", "|---|---|---|---|---|---|---|---|"]
    for r in [x for x in rows if x.get("method") == method]:
        out.append("| " + " | ".join(esc(x) for x in (r.get("rule_id"), r.get("author"), r.get("context_tf"), r.get("evidence_class"), "; ".join(r.get("code_refs") or []) or "—", r.get("implementation_status"), r.get("conformity"), "; ".join(r.get("missing_parameters") or []) or "—")) + " |")
    out.append("")
(ROOT / "docs" / "methodology" / "TRACEABILITY.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"rules={len(rows)}", dict(st))
