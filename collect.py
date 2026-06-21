"""텔레그램 채널에서 최근 메시지를 수집해 JSON 배열로 반환/저장."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import load_config, output_dir, telegram_credentials
from fetch import extract_urls, fetch_many


async def _collect_channel(client: TelegramClient, channel, cutoff_utc, tz, limit):
    """단일 채널에서 cutoff 이후 메시지를 수집."""
    items = []
    try:
        entity = await client.get_entity(channel)
    except Exception as e:  # noqa: BLE001
        print(f"  ! 채널 접근 실패 {channel!r}: {e}")
        return items

    title = getattr(entity, "title", None) or str(channel)
    username = getattr(entity, "username", None)

    count = 0
    async for msg in client.iter_messages(entity, limit=limit):
        if msg.date < cutoff_utc:
            break
        text = (msg.message or "").strip()
        if not text:
            continue  # 텍스트 없는 미디어/서비스 메시지는 건너뜀
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
    print(f"  · {title}: {count}건")
    return items


async def collect() -> list[dict]:
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=cfg["lookback_hours"])
    api_id, api_hash, session = telegram_credentials()
    limit = cfg["max_messages_per_channel"]

    all_items: list[dict] = []
    print(f"수집 시작 (최근 {cfg['lookback_hours']}시간, 채널 {len(cfg['channels'])}개)")
    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        for channel in cfg["channels"]:
            all_items.extend(
                await _collect_channel(client, channel, cutoff_utc, tz, limit)
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
