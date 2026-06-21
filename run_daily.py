"""데일리 마켓 브리핑 파이프라인: 수집 → 생성 → 전달.

매일 cron 으로 실행하는 진입점.

옵션:
  --no-deliver     텔레그램 전송 생략 (파일만 생성)
  --no-search-ctx  직전 브리핑 요약을 맥락으로 넘기지 않음
  --raw PATH       수집을 건너뛰고 기존 raw JSON 으로 생성만 수행
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from collect import collect, save_raw
from config import load_config, output_dir
from deliver import deliver
from generate import generate_briefing


def _today_str(cfg: dict) -> str:
    return datetime.now(ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d")


def extract_tldr(briefing_md: str) -> str | None:
    """브리핑 마크다운에서 TL;DR 섹션만 추출 (다음 브리핑 맥락용)."""
    m = re.search(r"###\s*📌\s*TL;DR.*?(?=\n###\s|\Z)", briefing_md, re.S)
    return m.group(0).strip() if m else None


def latest_previous_summary(today: str) -> str | None:
    """가장 최근(오늘 제외) 브리핑 파일의 TL;DR 을 반환."""
    files = sorted(output_dir().glob("briefing_*.md"))
    for path in reversed(files):
        if path.name == f"briefing_{today}.md":
            continue
        return extract_tldr(path.read_text(encoding="utf-8"))
    return None


def save_briefing(text: str, date_str: str) -> Path:
    path = output_dir() / f"briefing_{date_str}.md"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="데일리 마켓 브리핑 파이프라인")
    ap.add_argument("--no-deliver", action="store_true", help="텔레그램 전송 생략")
    ap.add_argument("--no-search-ctx", action="store_true", help="직전 브리핑 맥락 미사용")
    ap.add_argument("--raw", metavar="PATH", help="기존 raw JSON 으로 생성만 수행")
    args = ap.parse_args()

    cfg = load_config()
    today = _today_str(cfg)

    # 1) 수집
    if args.raw:
        items = json.loads(Path(args.raw).read_text(encoding="utf-8"))
        print(f"기존 raw 사용: {args.raw} ({len(items)}건)")
    else:
        items = asyncio.run(collect())
        save_raw(items, today)

    if not items:
        print("수집된 메시지가 없습니다. 채널 설정/세션을 확인하세요. 종료.")
        return

    # 2) 직전 브리핑 맥락
    prev = None
    if cfg["keep_previous_summary"] and not args.no_search_ctx:
        prev = latest_previous_summary(today)
        if prev:
            print("직전 브리핑 TL;DR 을 맥락으로 전달")

    # 3) 생성
    print("Claude 브리핑 생성 중...")
    briefing = generate_briefing(items, prev_summary=prev, focus=cfg.get("focus") or None)
    path = save_briefing(briefing, today)
    print("브리핑 저장:", path)

    # 4) 전달
    if args.no_deliver:
        print("(--no-deliver) 전송 생략")
        return
    header = f"📰 데일리 마켓 브리핑 — {today}"
    asyncio.run(deliver(briefing, header=header))


if __name__ == "__main__":
    main()
