"""데일리 마켓 브리핑 파이프라인: 수집 → 생성 → 전달.

매일 cron 으로 실행하는 진입점.

옵션:
  --slot HH        실행할 시간대 슬롯(예: 07/12/15/17). 생략 시 현재 KST 시각에 가장 가까운 슬롯.
  --no-deliver     텔레그램 전송 생략 (파일만 생성)
  --no-search-ctx  직전 브리핑 요약을 맥락으로 넘기지 않음
  --raw PATH       수집을 건너뛰고 기존 raw JSON 으로 생성만 수행
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from collect import collect, save_raw
from config import current_slot, load_config, output_dir, slot_by_name
from deliver import build_teaser, deliver
from generate import generate_briefing, summarize_feed
from insights import build_core_markdown


def _today_str(cfg: dict) -> str:
    return datetime.now(ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d")


def extract_tldr(briefing_md: str) -> str | None:
    """브리핑 마크다운에서 TL;DR 섹션만 추출 (다음 브리핑 맥락용)."""
    m = re.search(r"###\s*📌\s*TL;DR.*?(?=\n###\s|\Z)", briefing_md, re.S)
    return m.group(0).strip() if m else None


def latest_previous_summary(key: str) -> str | None:
    """가장 최근(현재 슬롯 제외) 브리핑 파일의 TL;DR 을 반환."""
    files = sorted(output_dir().glob("briefing_*.md"))
    for path in reversed(files):
        if path.name == f"briefing_{key}.md":
            continue
        return extract_tldr(path.read_text(encoding="utf-8"))
    return None


def save_briefing(text: str, key: str) -> Path:
    path = output_dir() / f"briefing_{key}.md"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="데일리 마켓 브리핑 파이프라인")
    ap.add_argument("--slot", metavar="HH", help="시간대 슬롯(07/12/15/17). 생략 시 현재 시각 기준 자동")
    ap.add_argument("--no-deliver", action="store_true", help="텔레그램 전송 생략")
    ap.add_argument("--no-search-ctx", action="store_true", help="직전 브리핑 맥락 미사용")
    ap.add_argument("--raw", metavar="PATH", help="기존 raw JSON 으로 생성만 수행")
    args = ap.parse_args()

    cfg = load_config()
    today = _today_str(cfg)
    slot = slot_by_name(args.slot, cfg) if args.slot else current_slot(cfg)
    key = f"{today}_{slot['name']}"  # 예: 2026-06-24_17
    print(f"▶ 슬롯 {slot['name']}시 (최근 {slot['lookback_hours']}시간) — key={key}")

    # 1) 수집 (+ 기사 본문 추출). raw 를 먼저 저장 → 이후 단계가 실패해도 '전체 피드'는 살아있음.
    if args.raw:
        items = json.loads(Path(args.raw).read_text(encoding="utf-8"))
        print(f"기존 raw 사용: {args.raw} ({len(items)}건)")
    else:
        items = asyncio.run(collect(lookback_hours=slot["lookback_hours"]))
        save_raw(items, key)

    if not items:
        print("수집된 메시지가 없습니다. 채널 설정/세션을 확인하세요. 종료.")
        return

    label = f"{today} {slot['name']}시"  # 폴백 핵심·티저 양쪽에서 사용
    # 이 슬롯에서 유료 Claude(요약+AI 브리핑)를 쓸지. 비용절감: 밤사이(07시)만 true 권장.
    use_ai = slot.get("ai", True)

    # 2) 피드 항목별 AI 요약 — 유료 슬롯에서만. (아니면 피드는 원문 유지, 토큰 0)
    if use_ai:
        print("피드 요약 중...")
        items = summarize_feed(items)
        save_raw(items, key)  # 요약 반영해 재저장
    else:
        print(f"슬롯 {slot['name']}시: 무료 모드(ai:false) — 요약/AI 브리핑 생략, 키워드 핵심 사용")

    # 3) 핵심 브리핑 — 유료 슬롯은 AI 생성(실패 시 폴백), 무료 슬롯은 바로 키워드 핵심.
    briefing = None
    if use_ai:
        prev = None
        if cfg["keep_previous_summary"] and not args.no_search_ctx:
            prev = latest_previous_summary(key)
            if prev:
                print("직전 브리핑 핵심을 맥락으로 전달")
        try:
            print("핵심 브리핑 생성 중...")
            briefing = generate_briefing(items, prev_summary=prev, focus=cfg.get("focus") or None)
        except Exception as e:  # noqa: BLE001
            print(f"AI 브리핑 생성 실패 → 자동 추출 핵심으로 대체: {str(e)[:140]}")
    if not briefing:
        # 여러 채널에서 반복 언급된 키워드 = 그날의 핵심 (토큰 0). 핵심 탭이 비지 않게 항상 채운다.
        briefing = build_core_markdown(items, label)
    print("브리핑 저장:", save_briefing(briefing, key))

    # 4) 텔레그램 전달
    if args.no_deliver:
        print("(--no-deliver) 전송 생략")
        return

    # 텔레그램 메시지에 넣을 대시보드 링크 — 비번을 #pw= 로 담아 탭 한 번에 열리게
    url = cfg.get("dashboard_url")
    pw = os.environ.get("SITE_PASSWORD")
    dash = f"{url}#pw={quote(pw)}" if (url and pw) else url

    # 텔레그램엔 짧은 티저 카드(핵심 헤드라인 + 링크)만. 전문은 웹 대시보드에서.
    asyncio.run(deliver(build_teaser(briefing, label, dash)))


if __name__ == "__main__":
    main()
