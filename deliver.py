"""생성된 브리핑을 텔레그램(본인 Saved Messages 등)으로 전송."""
from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import load_config, telegram_credentials

# 텔레그램 단일 메시지 길이 한도(4096)보다 약간 여유를 둠.
CHUNK_LIMIT = 3900


def split_message(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """줄/문단 경계를 우선해 limit 이하 조각으로 분할."""
    chunks: list[str] = []
    buf = ""
    for line in text.split("\n"):
        # 한 줄 자체가 limit 보다 길면 강제로 잘라낸다.
        while len(line) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(buf) + len(line) + 1 > limit:
            chunks.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        chunks.append(buf)
    return chunks


async def deliver(text: str, header: str | None = None) -> None:
    cfg = load_config()
    api_id, api_hash, session = telegram_credentials()
    target = cfg["deliver_to"]

    body = f"{header}\n\n{text}" if header else text
    chunks = split_message(body)

    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        for i, chunk in enumerate(chunks, 1):
            suffix = f"\n\n— ({i}/{len(chunks)})" if len(chunks) > 1 else ""
            # parse_mode=None: 마크다운 기호(###, ** 등)를 그대로 평문 전송해 엔티티 오류 방지.
            await client.send_message(target, chunk + suffix, parse_mode=None)
    print(f"전달 완료: {target} 로 {len(chunks)}개 메시지 전송")


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        raise SystemExit("사용법: python deliver.py <브리핑.md 경로>")
    with open(src, "r", encoding="utf-8") as f:
        asyncio.run(deliver(f.read()))
