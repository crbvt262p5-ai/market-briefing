"""설정/환경 로딩 공통 유틸."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

load_dotenv(ROOT / ".env")


def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("channels", [])
    cfg.setdefault("lookback_hours", 24)
    cfg.setdefault("timezone", "Asia/Seoul")
    cfg.setdefault("output_dir", "briefings")
    cfg.setdefault("deliver_to", "me")
    cfg.setdefault("keep_previous_summary", True)
    cfg.setdefault("focus", "")
    cfg.setdefault("max_messages_per_channel", 200)
    return cfg


def output_dir() -> Path:
    d = ROOT / load_config()["output_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(
            f"환경변수 {name} 가 설정되지 않았습니다. .env 파일을 확인하세요 "
            f"(.env.example 참고)."
        )
    return val


def telegram_credentials() -> tuple[int, str, str]:
    api_id = int(require_env("TELEGRAM_API_ID"))
    api_hash = require_env("TELEGRAM_API_HASH")
    session = require_env("TELEGRAM_SESSION")
    return api_id, api_hash, session
