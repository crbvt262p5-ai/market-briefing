"""설정/환경 로딩 공통 유틸."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

load_dotenv(ROOT / ".env")

# 슬롯 미지정 시 기본값(KST). 직전 슬롯 이후만 다루도록 lookback 을 잡았다.
DEFAULT_SLOTS = [
    {"name": "07", "lookback_hours": 14},  # 전날 17시~ (밤사이 미국장)
    {"name": "11", "lookback_hours": 4},   # 07시~
    {"name": "15", "lookback_hours": 4},   # 11시~
    {"name": "17", "lookback_hours": 2},   # 15시~
]


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
    cfg.setdefault("slots", DEFAULT_SLOTS)
    cfg.setdefault("exclude_patterns", [])
    return cfg


def slots(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    return cfg.get("slots") or DEFAULT_SLOTS


def current_slot(cfg: dict | None = None, now: datetime | None = None) -> dict:
    """현재 KST 시각에 가장 가까운 슬롯을 고른다(cron 시각이 조금 어긋나도 안전)."""
    cfg = cfg or load_config()
    sl = slots(cfg)
    if now is None:
        now = datetime.now(ZoneInfo(cfg["timezone"]))
    hour = now.hour + now.minute / 60
    return min(sl, key=lambda s: abs(int(s["name"]) - hour))


def slot_by_name(name: str, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    for s in slots(cfg):
        if str(s["name"]) == str(name):
            return s
    raise SystemExit(f"슬롯 {name!r} 가 config.yaml 의 slots 에 없습니다.")


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
