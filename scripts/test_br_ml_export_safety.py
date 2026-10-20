"""B&R production ML export safety regression; never needs live credentials."""
import ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/"office_br"/"production_ml_export.py").read_text(encoding="utf-8")
tree=ast.parse(source)
def test_export_is_valid_python():
    assert tree
def test_export_checks_before_writing():
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="main")
    guards=[n.lineno for n in ast.walk(main) if isinstance(n,ast.Raise)]
    writes=[n.lineno for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="write_text"]
    assert guards and writes and min(guards)<min(writes)
def test_atomic_publish():
    assert "temporary.replace(target)" in source
if __name__=="__main__":
    test_export_is_valid_python()
    test_export_checks_before_writing()
    test_atomic_publish()
    print("OK")
