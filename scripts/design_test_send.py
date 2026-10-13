#!/usr/bin/env python3
"""ONE-OFF design test (temporary): send ONE clearly-labelled Telegram message with the new READY PNG card.

Frozen levels of an earlier TIA LONG (fixture) -> office_ready_card.render (the production renderer of #242)
-> Telegram sendPhoto with the "📊 Сценарій" button. It creates NO READY, trade, lifecycle event or DB row,
imports no DB code, and never prints the token. Without TG_BOT_TOKEN / OFFICE_CHAT_ID it stops WITHOUT sending.
Usage: python scripts/design_test_send.py [--dry-run]
"""
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TITLE = "🧪 ТЕСТ ДИЗАЙНУ — НЕ ТОРГОВИЙ СИГНАЛ"


def fail(msg, code=1):
    print(f"STOP: {msg}")
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        Path(out).write_text(f"### Design test — STOPPED\n\n{msg}\n", encoding="utf-8")
    sys.exit(code)


def num(x):
    import office_ready_card as card
    return card._num(x, "TIAUSDT")


def main():
    dry = "--dry-run" in sys.argv
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat = (os.environ.get("OFFICE_CHAT_ID") or "").strip()
    missing = [n for n, v in (("TG_BOT_TOKEN", token), ("OFFICE_CHAT_ID", chat)) if not v]
    if missing and not dry:
        fail("відсутні секрети GitHub Actions: " + ", ".join(missing) + ". Нічого не відправлено.", 2)
    fx = json.loads((ROOT / "scripts/fixtures/tia_long_frozen.json").read_text(encoding="utf-8"))
    import office_ready_card as card
    tg = fx["targets"]
    path = str(ROOT / "design_test_card.png")
    res = card.render(symbol=fx["symbol"], direction=fx["direction"], candles=fx["chart_candles"], entry=fx["entry"], zone=fx["zone"],
                      sl=fx["sl"], tp1=tg[0]["p"], tp2=None, tp3=None, ready_price=fx["entry"], key_level=fx["trigger_level"],
                      key_label="рівень", path=path)
    if not res.get("ok"):
        fail("графіка не створена: " + str(res.get("reason")))
    from PIL import Image
    im = Image.open(path)
    # The compact "ENTRY / TP1 / SL" graphic (#242) is 1000x1230 at default width; the plain chart is 1000x800.
    # render() swallows composition errors, so the template is verified by the resulting size — never fall back to the old card.
    if im.size != (1000, 1230):
        fail(f"нова картка (#242) не зібрана: розмір {im.size}, очікувалось (1000, 1230). Відправлення скасовано.")
    png = Path(path).read_bytes()
    sha = hashlib.sha256(png).hexdigest()
    entry, sl, tp1 = float(fx["entry"]), float(fx["sl"]), float(tg[0]["p"])
    rr = abs(tp1 - entry) / abs(entry - sl)
    caption = (f"{TITLE}\n\n🟢 TIA · LONG — заморожені рівні попереднього сигналу, новий READY не створювався.\n"
               f"Вхід {num(fx['zone'][0])}–{num(fx['zone'][1])} · SL {num(sl)} · TP1 {num(tp1)} · R/R 1:{rr:.2f}\n"
               "Лише перевірка вигляду картки в Telegram. Не торгувати.")
    from office_telegram_policy import mini_app_button
    base = os.environ.get("OFFICE_MINI_APP_URL", "").strip() or "https://ai-office-miniapp.onrender.com"
    kb = mini_app_button(symbol=fx["symbol"], scenario_id=fx["scenario_id"], base_url=base)
    print(f"PNG ok: {im.size} sha256={sha[:16]} bytes={len(png)} renderer=office_ready_card.render(+_compose_telegram_card)")
    print("caption:\n" + caption)
    print("button:", json.dumps(kb, ensure_ascii=False))
    if dry:
        print("DRY RUN: нічого не відправлено.")
        return
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", chat), ("caption", caption), ("reply_markup", json.dumps(kb, ensure_ascii=False))):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="design_test_card.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + png + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = {"ok": False, "http": e.code, "description": json.loads(e.read().decode("utf-8", "replace") or "{}").get("description")}
    except Exception as e:  # noqa: BLE001  (never echo the URL: it contains the token)
        fail(f"мережева помилка Telegram: {type(e).__name__}")
    if not body.get("ok"):
        fail(f"Telegram API відмовив: {body.get('http')} {body.get('description')}")
    m = body["result"]
    sent = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(m.get("date", t0)))
    photo = max(m.get("photo") or [{}], key=lambda p: p.get("file_size", 0))
    lines = [f"Telegram API ok=true", f"chat_id={m['chat']['id']}", f"message_id={m['message_id']}", f"sent_at={sent}",
             f"photo={photo.get('width')}x{photo.get('height')} file_size={photo.get('file_size')}",
             f"sent_png_sha256={sha}", f"button={json.dumps(kb, ensure_ascii=False)}"]
    print("\n".join(lines))
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        Path(out).write_text("### Design test — SENT\n\n```\n" + "\n".join(lines) + "\n```\n", encoding="utf-8")


if __name__ == "__main__":
    main()
