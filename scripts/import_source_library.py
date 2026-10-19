#!/usr/bin/env python3
"""Verify and extract a user-provided AI Office source archive locally.

Does not fetch remote content, does not change any trading rules.
Use only in an authorized private workspace; respect source copyrights.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

REQUIRED = {
    "INDEX.csv", "COUNTS.json",
    "00_READ_FIRST_PROVENANCE_CORRECTION.md", "PROVENANCE_OVERRIDES.csv",
}
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path, help="path to ORIGINAL corrected ZIP")
    p.add_argument("--output", type=Path, default=Path("source_library"))
    p.add_argument("--extract", action="store_true",
                   help="extract originals into output/raw/2026-10-11")
    a = p.parse_args()
    with ZipFile(a.archive) as z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        names = [i.filename for i in entries]
        if len(names) != len(set(names)):
            raise SystemExit("Duplicate paths in ZIP")
        missing = REQUIRED.difference(names)
        if missing:
            raise SystemExit(f"Missing required manifests: {sorted(missing)}")
        originals = [i for i in entries if i.filename.startswith("screenshots/")]
        if len(originals) != 415:
            raise SystemExit(f"Expected 415 screenshots, found {len(originals)}")
        hashes = []
        for i in entries:
            path = PurePosixPath(i.filename)
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit(f"Unsafe path in ZIP: {i.filename}")
            data = z.read(i)
            hashes.append({"path": i.filename, "sha256": sha256(data), "bytes": len(data)})
            if a.extract:
                dest = a.output / "raw" / "2026-10-11" / i.filename
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        dest_manifest = a.output / "manifests" / "2026-10-11"
        dest_manifest.mkdir(parents=True, exist_ok=True)
        for name in sorted(REQUIRED):
            (dest_manifest / name).write_bytes(z.read(name))
        (dest_manifest / "hashes.json").write_text(
            json.dumps(hashes, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"VERIFIED: {len(originals)} screenshots, {len(entries)} source files")
    print(f"MANIFEST: {dest_manifest / 'hashes.json'}")
    print("ORIGINALS_EXTRACTED" if a.extract else "ORIGINALS_NOT_EXTRACTED (use --extract)")

if __name__ == "__main__":
    main()
