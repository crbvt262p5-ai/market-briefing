"""텔레그램 채널에서 최근 메시지를 수집해 JSON 배열로 반환/저장."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import load_config, output_dir, telegram_credentials
from fetch import extract_urls, fetch_many

_LETTER_RE = re.compile(r"[가-힣A-Za-z]")
_URL_RE = re.compile(r"https?://\S+")


def _is_noise(text: str, patterns: list[str]) -> bool:
    """제외 패턴(부분일치) 중 하나라도 걸리면 노이즈로 간주."""
    return any(p and p in text for p in patterns)


def _is_low_signal(text: str) -> bool:
    """기호·숫자만 많고 해석 가능한 언어 텍스트가 거의 없는 메시지면 True(수집 스킵).

    URL 제거 후 한글/영문 글자 수와 비중을 본다 — 표·호가·구분선·이모지 도배 등
    '읽어도 의미 없는' 메시지를 걸러 하위 단계(요약/브리핑)의 처리량을 아낀다."""
    body = _URL_RE.sub(" ", text)
    letters = len(_LETTER_RE.findall(body))
    compact = len("".join(body.split()))  # 공백 제외 전체 문자 수
    if compact == 0:
        return True
    # 글자가 거의 없거나(<3), 공백 제외 문자 중 글자 비중이 20% 미만이면 해석 곤란한 잡음.
    # 하한을 낮게 둬 'CPI 3.1%' 같은 짧지만 유효한 헤드라인의 오탐을 피한다.
    return letters < 3 or (letters / compact) < 0.20


async def _collect_channel(client: TelegramClient, channel, cutoff_utc, tz, limit, exclude):
    """단일 채널에서 cutoff 이후 메시지를 수집(노이즈 패턴은 제외)."""
    items = []
    try:
        entity = await client.get_entity(channel)
    except Exception as e:  # noqa: BLE001
        print(f"  ! 채널 접근 실패 {channel!r}: {e}")
        return items

    title = getattr(entity, "title", None) or str(channel)
    username = getattr(entity, "username", None)

    count = 0
    skipped = 0
    low = 0
    async for msg in client.iter_messages(entity, limit=limit):
        if msg.date < cutoff_utc:
            break
        text = (msg.message or "").strip()
        if not text:
            continue  # 텍스트 없는 미디어/서비스 메시지는 건너뜀
        if _is_noise(text, exclude):
            skipped += 1
            continue  # [AI시그널] 자동 도배 등 노이즈 제외
        if _is_low_signal(text):
            low += 1
            continue  # 기호·숫자만 많고 해석 어려운 메시지는 스킵(처리량 절약)
        link = f"https://t.me/{username}/{msg.id}" if username else None
        items.append(
            {
                "timestamp": msg.date.astimezone(tz).isoformat(),
                "channel": title,
                "text": text,
                "link": link,
                "media_caption": None,
                "urls": extract_urls(text),
            }
        )
        count += 1
    tails = []
    if skipped:
        tails.append(f"노이즈 {skipped}")
    if low:
        tails.append(f"저신호 {low}")
    tail = f" ({', '.join(tails)} 제외)" if tails else ""
    print(f"  · {title}: {count}건{tail}")
    return items


async def collect(lookback_hours: float | None = None) -> list[dict]:
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    lb = cfg["lookback_hours"] if lookback_hours is None else lookback_hours
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=lb)
    api_id, api_hash, session = telegram_credentials()
    limit = cfg["max_messages_per_channel"]
    exclude = cfg.get("exclude_patterns") or []

    all_items: list[dict] = []
    print(f"수집 시작 (최근 {lb}시간, 채널 {len(cfg['channels'])}개)")
    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        for channel in cfg["channels"]:
            all_items.extend(
                await _collect_channel(client, channel, cutoff_utc, tz, limit, exclude)
            )

    all_items.sort(key=lambda x: x["timestamp"])
    print(f"수집 완료: 총 {len(all_items)}건")

    # 링크된 기사/리포트 본문 추출 (헤드라인이 아니라 실제 내용)
    all_urls = list({u for it in all_items for u in it["urls"]})
    if all_urls:
        print(f"본문 추출: 외부 링크 {len(all_urls)}개...")
        arts = fetch_many(all_urls)
        ok = sum(1 for a in arts.values() if a.get("text"))
        print(f"  본문 확보 {ok}건 / PDF·기타 {len(arts) - ok}건")
        for it in all_items:
            it["articles"] = [arts[u] for u in it["urls"] if u in arts]
    else:
        for it in all_items:
            it["articles"] = []
    return all_items


def save_raw(items: list[dict], date_str: str) -> str:
    path = output_dir() / f"raw_{date_str}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return str(path)


if __name__ == "__main__":
    today = datetime.now(ZoneInfo(load_config()["timezone"])).strftime("%Y-%m-%d")
    data = asyncio.run(collect())
    print("저장:", save_raw(data, today))
