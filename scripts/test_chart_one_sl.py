"""Mini App: на графіку одного сценарію — лише ОДНА лінія «Стоп-лосс». Структурна інвалідація — окрема пунктирна лінія з іншою назвою,
вимкнена за замовчуванням і вмикається окремим перемикачем. Статична перевірка джерела."""
import os, re, sys
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "office_web", "mini_v2.html"), encoding="utf-8").read()
bad = 0


def check(name, ok):
    global bad
    print(("OK   " if ok else "FAIL ") + name)
    bad += 0 if ok else 1


check("шар inval існує і вимкнений за замовчуванням", "inval:lsGet('ao_inv1','0')==='1'" in src)
check("жодних підписів «Стоп 1 (поточний)» на графіку", "Стоп 1 (поточний)" not in src)
check("додаткові лінії лише під шаром inval", "if(S.layers.inval) (s.__extra||[]).forEach" in src and "if(S.layers.sl) (s.__extra" not in src)
check("додаткова лінія пунктирна і названа не-SL", "'Інвалідація структури (не SL)',3)" in src)
check("в __extra лише структурний варіант v2", "['v2'].filter(k=>stp[k]" in src and "['v2','v3']" not in src)
check("кнопка перемикача інвалідації є в обох панелях", src.count('data-l="inval"') == 2)
check("лінія SL одна", len(re.findall(r"line\(lv\.sl,", src)) == 1)
sys.exit(1 if bad else 0)
