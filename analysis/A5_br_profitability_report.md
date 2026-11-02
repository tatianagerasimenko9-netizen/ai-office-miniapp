# A5: B&R profitability — контрольний зріз 02.11.2026

Джерело: read-only production PostgreSQL `br_test_signal`, `br_test_event`, звірка з `MASTER_CHECKLIST.md`. **Не є валідацією за біржовими M1-свічками.**

## Дані
- 1118 рядків; 970 унікальних планів після дедуплікації по symbol+direction+created_ts (секунда)+entry/sl (6dp); 148 повторних рядків.
- 869 планів з ENTRY; 842 однозначні TP1/SL; 22 AMBIGUOUS; 101 без ENTRY; ще 5 із ENTRY без визначеного результату.
- Модель: TP1 раніше SL => `abs(TP1-entry)/abs(entry-SL)`; інакше `-1R`. Витрати `0.0015*entry/abs(entry-SL)` R. AMBIGUOUS виключені, а не зараховані як TP.
- Загалом для 842 планів: **-0.543R**, 95% cluster-bootstrap CI [-0.645;-0.433], 499 кластерів (15m-bar + direction). Це 1600 відтворюваних bootstrap-ітерацій; CI є попереднім, не поправленим на вибір багатьох гіпотез.

## UTC sessions (FIXED comparison windows; not DST-adjusted venue boundaries)
| UTC | n | clusters | mean net R | 95% CI |
|---|---:|---:|---:|---|
| 00–07 Asia | 235 | 149 | -0.688 | [-0.868;-0.488] |
| 07–13 London proxy | 221 | 133 | -0.715 | [-0.892;-0.533] |
| 13–17 Overlap proxy | 178 | 90 | -0.155 | [-0.390;+0.068] |
| 17–21 NY late proxy | 126 | 75 | -0.560 | [-0.827;-0.291] |
| 21–00 Late | 82 | 52 | -0.478 | [-0.869;-0.078] |

## Purged/time split caution
Chronological illustration (Kyiv local date):
- Before 25 Oct: 490 plans, mean -0.494R.
- From 25 Oct: 352 plans, mean -0.611R.
- Kyiv 17:00–18:59: early 68 plans / 31 clusters, +0.253R CI [-0.078;+0.515]; late 19 plans / 11 clusters, -0.620R CI [-0.991;-0.143].
- **Not a fully purged holdout**: open positions crossing split boundary not removed; 17–19 selected partly from prior exploratory inspection. No profitable-hour claim.

## Stops
| Stop width | plans | model net R for resolved |
|---|---:|---:|
| <0.3% | 318 | -0.942 |
| 0.3–0.5% | 253 | -0.464 |
| 0.5–0.8% | 207 | -0.372 |
| 0.8–1.2% | 130 | -0.264 |
| >=1.2% | 62 | -0.027 |

## Missing evidence / NOT VERIFIED
Macro news ±30/60 min, stop-hunt fraction, H1/H4/D1 alternate SL replay, random/time-shift/no-retest control, cluster multiple-testing correction and robust purged holdout, execution cost sensitivity, position management 30/40/30. Do not claim these are DONE.

## A4 / A7
A4: use `analysis/A4_duplicate_audit.sql` against production before tuning PR #284. PR #284 includes live suppression: **do not merge** without independent replay and C approval.
A7: `analysis/br_profitability_shadow.py` is PURE, not imported by live and cannot suppress orders or alerts; all thresholds HYPOTHESIS; no verified HTF swing available => null, not guessed. Tests in `scripts/test_br_profitability_shadow.py`.

## Control / acceptance
A4: PR #284 still draft and NOT MERGED; only measurement is addressed by this branch.
A5: PARTIAL report; data/br_plans.psv still requires A6 production export; full 24h tables, purged holdout and controls remain open.
A7: PR_OPEN after tests and C review; pure flags implemented, DB persistence not yet wired (would require explicit production-safety review).
