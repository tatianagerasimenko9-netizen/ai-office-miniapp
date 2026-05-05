from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parent
DEFAULT_CFG = ROOT / "office_relay_config.json"


def load_cfg(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def save_cfg(path: Path, cfg: Dict[str, Any]) -> None:
    merged: Dict[str, Any] = {}
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                merged.update(existing)
    except Exception:
        merged = {}

    for k, v in cfg.items():
        if k == "agent_bot_tokens" and isinstance(v, dict) and isinstance(merged.get("agent_bot_tokens"), dict):
            base_tokens = dict(merged.get("agent_bot_tokens") or {})
            base_tokens.update(v)
            merged[k] = base_tokens
        else:
            merged[k] = v

    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prompt_if_missing(cfg: Dict[str, Any], key_env: str, cfg_key: str, label: str) -> None:
    if os.getenv(key_env, "").strip():
        return
    tokens = cfg.get("agent_bot_tokens")
    if isinstance(tokens, dict) and str(tokens.get(cfg_key, "")).strip():
        return
    val = input(f"{label} (Enter to skip): ").strip()
    if not val:
        return
    if not isinstance(cfg.get("agent_bot_tokens"), dict):
        cfg["agent_bot_tokens"] = {}
    assert isinstance(cfg["agent_bot_tokens"], dict)
    cfg["agent_bot_tokens"][cfg_key] = val


def main() -> int:
    cfg_path = Path(os.getenv("OFFICE_RELAY_CONFIG", str(DEFAULT_CFG))).expanduser()
    cfg = load_cfg(cfg_path)

    interactive = os.getenv("MULTIBOT_INTERACTIVE", "").strip() == "1"
    keys_needed = ("lev", "maks", "news", "daryna", "marko", "olesya")
    tokens = cfg.get("agent_bot_tokens") if isinstance(cfg.get("agent_bot_tokens"), dict) else {}
    missing = [k for k in keys_needed if not (isinstance(tokens, dict) and str(tokens.get(k, "") or "").strip())]

    if missing and not interactive:
        print(f"[multibot] missing bot tokens: {', '.join(missing)}")
        print("[multibot] tip: set MULTIBOT_INTERACTIVE=1 once to enter missing tokens, or edit office_relay_config.json")

    # Optional one-time collection (only if missing).
    if interactive:
        prompt_if_missing(cfg, "AGENT_BOT_TOKEN_LEV", "lev", "LEV bot token")
        prompt_if_missing(cfg, "AGENT_BOT_TOKEN_MAKS", "maks", "MAKS bot token")
        prompt_if_missing(cfg, "AGENT_BOT_TOKEN_NEWS", "news", "NEWS bot token")
        prompt_if_missing(cfg, "AGENT_BOT_TOKEN_DARYNA", "daryna", "DARYNA bot token")
        prompt_if_missing(cfg, "AGENT_BOT_TOKEN_MARKO", "marko", "MARKO bot token")
        prompt_if_missing(cfg, "AGENT_BOT_TOKEN_OLESYA", "olesya", "OLESYA bot token")

    save_cfg(cfg_path, cfg)

    # Export tokens into env for office_relay_wizard.py / Telethon process.
    tokens = cfg.get("agent_bot_tokens")
    if isinstance(tokens, dict):
        mapping = {
            "lev": "AGENT_BOT_TOKEN_LEV",
            "maks": "AGENT_BOT_TOKEN_MAKS",
            "news": "AGENT_BOT_TOKEN_NEWS",
            "daryna": "AGENT_BOT_TOKEN_DARYNA",
            "marko": "AGENT_BOT_TOKEN_MARKO",
            "olesya": "AGENT_BOT_TOKEN_OLESYA",
        }
        for k, envk in mapping.items():
            v = str(tokens.get(k, "") or "").strip()
            if v:
                os.environ[envk] = v

    # Run relay wizard in the same folder.
    wizard = ROOT / "office_relay_wizard.py"
    return subprocess.call([sys.executable, str(wizard)], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())

