"""생성된 브리핑을 텔레그램(본인 Saved Messages 등)으로 전송."""
from __future__ import annotations

import asyncio
import html
import re

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import load_config, telegram_credentials

# 텔레그램 단일 메시지 길이 한도(4096)보다 약간 여유를 둠.
CHUNK_LIMIT = 3900

# 대시보드 렌더링용 구분선.
DIVIDER = "━━━━━━━━━━━━"
_HR_CHARS = {"-", "*", "_"}


def _inline(s: str) -> str:
    """이미 HTML 이스케이프된 문자열에서 **굵게**/*기울임*을 텔레그램 태그로 변환."""
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", s)
    return s


def to_telegram_html(md: str) -> str:
    """브리핑 마크다운을 텔레그램 HTML '대시보드' 형식으로 변환한다.

    - `#`~`###` 제목 → 위에 구분선 + <b>굵은 제목</b>
    - `---`/`***` 수평선 → 제거(제목이 구분을 담당)
    - `- `/`* ` 불릿 → `•`
    - `▸ ` 채널 헤더(다이제스트) → 굵게
    - **굵게**/*기울임* → <b>/<i>
    태그는 항상 한 줄 안에서 닫히므로 줄 경계로 분할해도 깨지지 않는다."""
    out: list[str] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        # 수평선(---, ***, ___)은 버린다 — 제목 위 구분선이 대신한다.
        if len(stripped) >= 3 and set(stripped) <= _HR_CHARS:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            out.append("")
            out.append(DIVIDER)
            out.append(f"<b>{_inline(html.escape(m.group(2)))}</b>")
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            out.append("• " + _inline(html.escape(m.group(1))))
            continue
        if stripped.startswith("▸ "):
            out.append(f"<b>{_inline(html.escape(stripped))}</b>")
            continue
        out.append(_inline(html.escape(line)))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    # 맨 앞에 붙은 구분선 제거(최상단 제목 위).
    if text.startswith(DIVIDER):
        text = text[len(DIVIDER):].lstrip("\n")
    return text


def build_digest(items: list[dict], date: str, dashboard_url: str | None = None) -> str:
    """AI 브리핑이 없을 때(크레딧 미충전) 보내는 '수집 피드 다이제스트'.

    채널별로 묶어 헤드라인 + 텔레그램 링크를 나열. 탭하면 텔레그램 원문으로 이동."""
    lines = [f"📰 마켓 피드 · {date}"]
    if dashboard_url:
        lines.append(f"🔗 대시보드: {dashboard_url}")
    lines.append(f"수집 {len(items)}건 · (AI 요약/브리핑은 크레딧 충전 시 자동 추가)")
    lines.append("━━━━━━━━━━")

    by_ch: dict[str, list[dict]] = {}
    for it in items:
        by_ch.setdefault(it.get("channel", "기타"), []).append(it)

    for ch, msgs in by_ch.items():
        lines.append(f"\n▸ {ch.strip('[] ')}")
        for it in msgs:
            head = next((ln for ln in (it.get("text", "") or "").splitlines() if ln.strip()), "")
            head = head[:90]
            link = it.get("link")
            lines.append(f"• {head}" + (f"\n  {link}" if link else ""))
    return "\n".join(lines)


def core_headlines(briefing_md: str, limit: int = 10) -> list[str]:
    """브리핑의 '📌 핵심' 섹션에서 각 불릿의 굵은 헤드라인을 뽑는다.

    키워드 핵심은 `**키워드** (N개 채널·M건)` 형태라, 뒤따르는 (…) 반복도 태그가
    있으면 함께 붙여 텔레그램 티저에서도 '여러 채널 반복' 맥락이 드러나게 한다."""
    m = re.search(r"###\s*📌[^\n]*\n(.*?)(?=\n###|\n---|\Z)", briefing_md, re.S)
    if not m:
        return []
    heads: list[str] = []
    for ln in m.group(1).splitlines():
        ln = ln.strip()
        if ln.startswith(("- ", "* ")):
            b = re.search(r"\*\*(.+?)\*\*\s*(\([^)]*\))?", ln)
            if b:
                head = b.group(1).strip()
                if b.group(2):
                    head = f"{head} {b.group(2)}"
            else:
                head = ln[2:].strip()
            heads.append(head[:80])
    return heads[:limit]


def build_teaser(briefing_md: str, label: str, dashboard_url: str | None) -> str:
    """텔레그램용 짧은 티저 카드 — 핵심 헤드라인 + 대시보드 링크. 전문은 웹에서."""
    heads = core_headlines(briefing_md)
    parts = [f"## 📊 마켓 브리핑 · {label}"]
    if heads:
        parts.append("### 오늘의 핵심\n" + "\n".join(f"- {h}" for h in heads))
    else:
        parts.append("_핵심 요약을 불러오지 못했습니다. 대시보드에서 확인하세요._")
    if dashboard_url:
        parts.append(f"👉 전체 브리핑·피드 대시보드 열기 (탭)\n{dashboard_url}")
    return "\n\n".join(parts)


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

    # 헤더는 최상단 제목으로(마크다운 h2 → 대시보드 굵은 제목), 본문과 함께 HTML 렌더.
    raw = f"## {header}\n\n{text}" if header else text
    body = to_telegram_html(raw)
    chunks = split_message(body)

    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        for i, chunk in enumerate(chunks, 1):
            suffix = f"\n\n<i>— ({i}/{len(chunks)})</i>" if len(chunks) > 1 else ""
            # parse_mode='html': 태그는 항상 한 줄 안에서 닫혀 분할해도 안전.
            await client.send_message(
                target, chunk + suffix, parse_mode="html", link_preview=False
            )
    print(f"전달 완료: {target} 로 {len(chunks)}개 메시지 전송")


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        raise SystemExit("사용법: python deliver.py <브리핑.md 경로>")
    with open(src, "r", encoding="utf-8") as f:
        asyncio.run(deliver(f.read()))
