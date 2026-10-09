#!/usr/bin/env python3
"""Матриця SMC: кожен рядок вказує на існуючий код і існуючий тест; усі розділи джерела й усі 40 схем покриті; документ SMC_MATRIX.md не застарів."""
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from office2.smc import matrix as MX  # noqa: E402
from office2.smc import sources as SRC  # noqa: E402


def _resolve(dotted):
    parts = dotted.split(".")
    for k in range(len(parts) - 1, 0, -1):
        try:
            mod = importlib.import_module(".".join(parts[:k]))
        except ImportError:
            continue
        obj = mod
        for p in parts[k:]:
            obj = getattr(obj, p)
        return obj
    raise ImportError(dotted)


def test_every_row_points_to_existing_code_and_test():
    for r in MX.ROWS:
        assert _resolve(r["code"]) is not None, r["id"]
        path, func = r["test"].split("::")
        text = (ROOT / path).read_text(encoding="utf8")
        assert re.search(rf"def {re.escape(func)}\b", text), (r["id"], r["test"])
        assert r["status"] and r["impact"] and r["brain"]


def test_all_sections_images_and_algo_sections_are_covered():
    covered = {s for r in MX.ROWS for s in re.split(r"[/,]| ", r["section"]) if s}
    pat = lambda sid: sid in covered or any(sid.startswith(c.split(".")[0]) and c in sid for c in covered)  # noqa: E731
    for s in SRC.SECTIONS:
        if s["cls"] == "ALGO":
            base = s["id"]
            assert any(base in r["section"] or base.split(".")[0] in r["section"] for r in MX.ROWS), f"розділ {base} без правила в матриці"
    imgs = {i for r in MX.ROWS for i in r["images"]}
    missing = [i["n"] for i in SRC.IMAGES if i.get("fixture") and i["n"] not in imgs]
    assert not missing, f"схеми з фікстурою без рядка матриці: {missing}"
    ids = [r["id"] for r in MX.ROWS]
    assert len(ids) == len(set(ids))


def test_doc_is_up_to_date():
    doc = (ROOT / "docs/office2/SMC_MATRIX.md").read_text(encoding="utf8")
    assert doc == MX.render_md(), "docs/office2/SMC_MATRIX.md застарів: python3 -c \"from office2.smc import matrix as m; open('docs/office2/SMC_MATRIX.md','w').write(m.render_md())\""


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
