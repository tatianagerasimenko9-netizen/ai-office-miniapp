"""Mini App: Office2 LIVE BETA — повний decision trace. Для кожного READY: РИНОК НА МОМЕНТ СИГНАЛУ (заморожений знімок) / РИНОК ЗАРАЗ / ЩО ЗМІНИЛОСЯ.
Знімок моменту сигналу ніколи не переписується; «зараз» береться з живого шару office2_shadow_state."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


def _rows(db: str, sql: str, args: tuple = ()) -> list:
    from office_bridge import _fetchall

    try:
        return _fetchall(db, sql, args)
    except Exception:  # noqa: BLE001
        return []


def _latest_state(db: str, symbol: str) -> Optional[Dict[str, Any]]:
    r = _rows(db, "SELECT ts_epoch, payload_json FROM office2_shadow_state WHERE symbol = ? ORDER BY ts_epoch DESC LIMIT 1", (symbol,))
    if not r:
        return None
    d = json.loads(r[0][1])
    d["ts_epoch"] = r[0][0]
    return d


def _milestones(db: str, sid: str) -> List[Dict[str, Any]]:
    out = []
    for (pj,) in _rows(db, "SELECT payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id = ? ORDER BY id ASC", (sid,)):
        try:
            out.append(json.loads(pj))
        except ValueError:
            pass
    return out


def what_changed(snap: Dict[str, Any], now_state: Optional[Dict[str, Any]], miles: List[Dict[str, Any]]) -> Dict[str, Any]:
    th = snap.get("thesis") or {}
    entry, sl = th.get("entry"), th.get("sl")
    out: Dict[str, Any] = {"levels_reached": [m.get("level") for m in miles]}
    if not now_state or not entry or sl is None:
        out["note"] = "поточних даних немає"
        return out
    px = now_state.get("price")
    risk = abs(entry - sl)
    sgn = 1.0 if snap.get("direction") == "LONG" else -1.0
    if px is not None and risk > 0:
        out["price_now"] = px
        out["move_pct"] = (px / entry - 1.0) * 100.0 * sgn
        out["move_r"] = (px - entry) * sgn / risk
        out["sl_distance_r"] = (px - sl) * sgn / risk
    mkt0 = ((snap.get("market_at_signal") or {}).get("market")) or {}
    mkt1 = now_state.get("market") or {}
    for k in ("btc_ret_1h", "breadth_up_4h", "median_vol_regime", "btc_reg4"):
        a, b = mkt0.get(k), mkt1.get(k)
        out[k] = {"at_signal": a, "now": b, "delta": (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None}
    return out


def payload(db: str, now: Optional[float] = None, focus: str = "") -> Dict[str, Any]:
    t = time.time() if now is None else now
    states = {r[0]: r[1] for r in _rows(db, "SELECT state, COUNT(*) FROM office2_live_scenario GROUP BY state")}
    last = _rows(db, "SELECT MAX(ts_epoch), COUNT(DISTINCT symbol) FROM office2_shadow_state WHERE ts_epoch > ?", (int(t - 3600),))
    scen = [{"id": r[0], "symbol": r[1], "direction": r[2], "kind": r[3], "state": r[4], "reason": r[5], "updated_ts": r[6]}
            for r in _rows(db, "SELECT scenario_id, symbol, direction, kind, state, reason, updated_ts FROM office2_live_scenario ORDER BY updated_ts DESC LIMIT 80")]
    sigs = []
    for sid, sym, d, ct, vu, status, msg, sj in _rows(db, "SELECT scenario_id, symbol, direction, created_ts, valid_until_ts, status, msg_id, snapshot_json FROM office2_live_signal ORDER BY created_ts DESC LIMIT 20"):
        snap = json.loads(sj or "{}")
        ns = _latest_state(db, sym)
        if not snap.get("alignment"):   # знімки до появи поля: узгодженість рахуємо з ЗАМОРОЖЕНИХ значень знімка (не з поточного ринку) і позначаємо це
            from office2 import align as AL

            ms = snap.get("market_at_signal") or {}
            snap["alignment"] = AL.alignment(d, ms.get("market") or {}, ms.get("relative") or {}, ((snap.get("context") or {}).get("htf")))
            snap["alignment_derived"] = True
        sigs.append({"id": sid, "symbol": sym, "direction": d, "created_ts": ct, "valid_until_ts": vu, "status": status, "telegram_msg_id": msg,
                     "frozen": {k: snap.get(k) for k in ("label", "evidence_status", "decided_utc", "why", "thesis", "market_at_signal", "trace", "context", "old_lev", "alignment", "alignment_derived")},
                     "market_now": ({"ts_epoch": ns.get("ts_epoch"), "price": ns.get("price"), "market": ns.get("market"), "ret_1h": ns.get("ret_1h"), "rs_vs_btc_1h": ns.get("rs_vs_btc_1h")} if ns else None),
                     "changed": what_changed(snap, ns, _milestones(db, sid))})
    from office2 import brain as B

    if focus:   # відкритий за посиланням сигнал — першим
        sigs.sort(key=lambda x: 0 if x["id"] == focus else 1)
    cnt = {r[0]: r[1] for r in _rows(db, "SELECT 'state', COUNT(*) FROM office2_shadow_state UNION ALL SELECT 'event', COUNT(*) FROM office2_shadow_event UNION ALL SELECT 'outcome', COUNT(*) FROM office2_shadow_outcome")}
    return {"ok": True, "now": t, "label": "OFFICE2 · LIVE BETA", "evidence_status": B.EVIDENCE_STATUS,
            "flags": {"OFFICE2_SHADOW": os.getenv("OFFICE2_SHADOW", ""), "OFFICE2_LIVE": os.getenv("OFFICE2_LIVE", ""), "OFFICE2_LIVE_DELIVERY": os.getenv("OFFICE2_LIVE_DELIVERY", ""),
                      "OFFICE_OLD_READY_DELIVERY": os.getenv("OFFICE_OLD_READY_DELIVERY", "1")},
            "scenario_counts": states, "last_cycle_ts": last[0][0] if last and last[0][0] else None, "symbols_last_hour": last[0][1] if last else 0, "collected": cnt,
            "signals": sigs, "scenarios": scen, "modules": B.MODULES, "focus": focus, "focus_found": bool(focus and any(x["id"] == focus for x in sigs))}


PAGE = """<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Office2 LIVE BETA</title>
<style>:root{--bg:#0f1420;--fg:#e8ecf3;--mu:#8a96ab;--card:#171e2e;--ln:#26304a;--g:#2ebd85;--r:#e5534b;--y:#f2c230;--b:#7aa2ff}
@media(prefers-color-scheme:light){:root{--bg:#f6f8fb;--fg:#162033;--mu:#5b6880;--card:#fff;--ln:#d8dfeb}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;padding:14px 16px 60px;max-width:880px;margin:auto}
h1{font-size:20px;margin:6px 0}h2{font-size:16px;margin:22px 0 8px}.mu{color:var(--mu)}.card{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:12px 14px;margin:10px 0}
.g{color:var(--g)}.r{color:var(--r)}.y{color:var(--y)}.b{color:var(--b)}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:4px 6px;border-bottom:1px solid var(--ln);text-align:left}
pre{white-space:pre-wrap;word-break:break-word;font-size:12px;margin:4px 0}details>summary{cursor:pointer;color:var(--b);margin:6px 0}.tag{display:inline-block;border:1px solid var(--ln);border-radius:8px;padding:0 6px;font-size:12px;margin-right:4px}</style></head>
<body><h1>OFFICE2 · LIVE BETA</h1><div><a href="/" style="color:var(--b)">← у Mini App</a></div><div class="mu" id="st">завантаження…</div><div id="sig"></div><h2>Сценарії</h2><div id="sc"></div><h2>Модулі мозку</h2><div id="mod"></div>
<script>
const f=(x,d=2)=>x==null?'—':(typeof x==='number'?x.toFixed(d).replace('.',','):x);
const dt=t=>t?new Date(t*1000).toLocaleString('uk-UA',{timeZone:'Europe/Kyiv'}):'—';
function J(x){return '<pre>'+JSON.stringify(x,null,1).replace(/</g,'&lt;')+'</pre>'}
const FQ=new URLSearchParams(location.search).get('id')||'';
fetch('/api/v2/office2'+(FQ?'?id='+encodeURIComponent(FQ):'')).then(r=>r.json()).then(d=>{
 const fl=d.flags;document.getElementById('st').innerHTML=`Статус доказовості: <b class="y">${d.evidence_status}</b> (decision-support, не доведена стратегія) · шар: ${fl.OFFICE2_LIVE==='1'?'<b class="g">ON</b>':'OFF'} · Telegram: ${fl.OFFICE2_LIVE_DELIVERY==='1'?'<b class="g">ON</b>':'OFF'} · старий READY користувачу: ${fl.OFFICE_OLD_READY_DELIVERY==='0'?'<b>OFF</b>':'ON'}<br>Останній цикл: ${dt(d.last_cycle_ts)} (Київ) · монет за год: ${d.symbols_last_hour} · зібрано: стани ${d.collected.state||0}, події ${d.collected.event||0}, наслідки ${d.collected.outcome||0}<br>Сценарії: ${Object.entries(d.scenario_counts).map(([k,v])=>`<span class="tag">${k} ${v}</span>`).join('')}`;
 document.getElementById('sig').innerHTML=(FQ&&!d.focus_found?'<div class="card r">Сигнал '+FQ+' не знайдено (можливо, старіший за 20 останніх).</div>':'')+(d.signals.length?'':'<div class="card mu">Сигналів Office2 ще не було.</div>')+d.signals.map(s=>{const fr=s.frozen,th=fr.thesis||{},c=s.changed||{},m0=(fr.market_at_signal||{}).market||{},m1=(s.market_now||{}).market||{};
 const tg=(th.targets||[]).map((t,i)=>`TP${i+1} ${f(t.p,6)} (${f(t.r,1)} R, ${t.kind})`).join(' · ');
 return `<div class="card" ${FQ&&s.id===FQ?'style="border-color:var(--b)"':''}><b class="${s.direction==='LONG'?'g':'r'}">${s.direction==='LONG'?'🟢 LONG':'🔴 SHORT'} · ${s.symbol}</b> <span class="tag">${s.status}</span> <span class="mu">${dt(s.created_ts)}</span>
 <div>${fr.why||''}</div><div class="mu">Вхід ${f(th.entry,6)} · SL ${f(th.sl,6)} (${f(th.risk_pct)}%) · ${tg}</div>
 <h3>Ринок на момент сигналу</h3><div>BTC ${f(m0.btc_ret_1h)}% /1г · breadth 4г ${f(m0.breadth_up_4h)} · режим вол. ${f(m0.median_vol_regime)} · відносна сила ${f(((fr.market_at_signal||{}).relative||{}).rs_vs_btc_1h)} п.п.</div>
 <h3>Узгодженість з напрямом</h3><div>${(fr.alignment||[]).map(a=>`<div class="${a.verdict.startsWith('ПРОТИ')?'r':a.verdict.startsWith('ЗА')?'g':'mu'}">${a.verdict.startsWith('ПРОТИ')?'⚠ ':a.verdict.startsWith('ЗА')?'✓ ':'· '}${a.text}</div>`).join('')||'<span class="mu">—</span>'}${fr.alignment_derived?'<div class="mu">(обчислено зі збережених значень знімка)</div>':''}</div>
 <h3>Ринок зараз</h3><div>ціна ${f(c.price_now,6)} · BTC ${f(m1.btc_ret_1h)}% /1г · breadth 4г ${f(m1.breadth_up_4h)}</div>
 <h3>Що змінилося</h3><div>рух від входу ${f(c.move_pct)}% (${f(c.move_r)} R) · до SL ${f(c.sl_distance_r)} R · події: ${(c.levels_reached||[]).join(', ')||'—'}<br>BTC: ${f((c.btc_ret_1h||{}).delta)} п.п. · breadth 4г: ${f((c.breadth_up_4h||{}).delta)}</div>
 <details ${FQ&&s.id===FQ?'open':''}><summary>Decision trace (заморожено)</summary>${J(fr.trace)}</details><details><summary>Теза і структурна інвалідація</summary>${J(th)}</details><details><summary>Повний контекст на момент сигналу</summary>${J(fr.context)}</details><details><summary>Старий Лев на ту саму монету</summary>${J(fr.old_lev)}</details></div>`}).join('');
 document.getElementById('sc').innerHTML='<table><tr><th>Стан</th><th>Монета</th><th>Напрям</th><th>Вид</th><th>Причина</th><th>Оновлено</th></tr>'+d.scenarios.map(s=>`<tr><td>${s.state}</td><td>${s.symbol}</td><td>${s.direction}</td><td>${s.kind}</td><td>${s.reason||''}</td><td>${dt(s.updated_ts)}</td></tr>`).join('')+'</table>';
 document.getElementById('mod').innerHTML=`<div class="card"><b class="g">Активні</b>: ${d.modules.active.join('; ')}<br><b class="y">Лише контекст</b>: ${d.modules.context_only.join('; ')}<br><b class="r">Недоступні сьогодні</b>: ${d.modules.unavailable_today.join('; ')}</div>`;
}).catch(e=>{document.getElementById('st').textContent='помилка: '+e});
</script></body></html>"""


def html() -> str:
    return PAGE
