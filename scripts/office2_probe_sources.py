#!/usr/bin/env python3
"""Розвідка доступності джерел «грошового потоку» в публічному архіві Binance (data.binance.vision; лише читання).
Друкує: які набори існують, для яких дат/символів, колонки та перші рядки (малі файли), розмір (великі — лише HEAD)."""
import io
import sys
import urllib.error
import urllib.request
import zipfile

BASE = "https://data.binance.vision/data/futures/um"
SYMS = ["BTCUSDT", "SOLUSDT", "ENAUSDT"]
CASES = [
    ("daily", "metrics", "{s}-metrics-{d}", ["2021-12-01", "2023-06-01", "2025-06-01", "2025-12-31"], True),
    ("monthly", "fundingRate", "{s}-fundingRate-{m}", ["2025-06", "2025-12", "2023-06"], True),
    ("daily", "liquidationSnapshot", "{s}-liquidationSnapshot-{d}", ["2021-12-01", "2023-06-01", "2025-06-01"], True),
    ("monthly", "liquidationSnapshot", "{s}-liquidationSnapshot-{m}", ["2021-12", "2023-06", "2025-06"], True),
    ("daily", "aggTrades", "{s}-aggTrades-{d}", ["2025-06-01"], False),
    ("daily", "bookTicker", "{s}-bookTicker-{d}", ["2025-06-01"], False),
    ("daily", "premiumIndexKlines", "{s}-1m-{d}", ["2025-06-01"], True),
]


def get(url, head):
    req = urllib.request.Request(url, method="HEAD" if head else "GET", headers={"User-Agent": "office2-research"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, int(r.headers.get("Content-Length", "0") or 0), (b"" if head else r.read())
    except urllib.error.HTTPError as e:
        return e.code, 0, b""
    except Exception as e:  # noqa: BLE001
        return -1, 0, str(e).encode()


def main() -> int:
    for freq, ds, pat, dates, small in CASES:
        for s in SYMS:
            for d in dates:
                name = pat.format(s=s, d=d, m=d)
                folder = f"premiumIndexKlines/{s}/1m" if ds == "premiumIndexKlines" else f"{ds}/{s}"
                url = f"{BASE}/{freq}/{folder}/{name}.zip"
                st, size, body = get(url, head=not small)
                line = f"{ds:20s} {freq:7s} {s:8s} {d:11s} HTTP {st} size={size}"
                if st == 200 and small and body:
                    try:
                        with zipfile.ZipFile(io.BytesIO(body)) as z:
                            with z.open(z.namelist()[0]) as f:
                                head3 = f.read(600).decode("utf-8", "replace").splitlines()[:3]
                        line += " | " + " ‖ ".join(head3)
                    except Exception as e:  # noqa: BLE001
                        line += f" | zip error {e}"
                print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
