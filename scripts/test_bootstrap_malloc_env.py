"""Bootstrap передає relay MALLOC_ARENA_MAX=2 (обмеження арен glibc проти фрагментації пам'яті на 512 МБ); явна змінна середовища не перезаписується; 0 вимикає."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import office_multibot_bootstrap as B

bad = 0


def check(name, ok):
    global bad
    print(("OK   " if ok else "FAIL ") + name)
    bad += 0 if ok else 1


for k in ("MALLOC_ARENA_MAX", "OFFICE_MALLOC_ARENA_MAX"):
    _os.environ.pop(k, None)
check("за замовчуванням MALLOC_ARENA_MAX=2", B.child_env().get("MALLOC_ARENA_MAX") == "2")
_os.environ["MALLOC_ARENA_MAX"] = "4"
check("явна MALLOC_ARENA_MAX не перезаписується", B.child_env().get("MALLOC_ARENA_MAX") == "4")
_os.environ.pop("MALLOC_ARENA_MAX")
_os.environ["OFFICE_MALLOC_ARENA_MAX"] = "0"
check("OFFICE_MALLOC_ARENA_MAX=0 вимикає", "MALLOC_ARENA_MAX" not in B.child_env())
print("ALL OK" if not bad else f"FAILED {bad}")
_sys.exit(1 if bad else 0)
