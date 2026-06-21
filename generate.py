"""수집된 텔레그램 JSON 을 Claude 로 분석해 마켓 브리핑(마크다운)을 생성."""
from __future__ import annotations

import json

import anthropic

from config import ROOT

MODEL = "claude-sonnet-4-6"  # 비용 절감(입력 $3/출력 $15). 품질↑ 원하면 claude-opus-4-8
# Opus 4.8/4.7/4.6 + Sonnet 4.6 에서 동적 필터링을 지원하는 최신 웹검색 도구.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


def _load_system_prompt() -> str:
    with open(ROOT / "prompt.md", "r", encoding="utf-8") as f:
        return f.read()


def _build_user_message(items: list[dict], prev_summary: str | None, focus: str | None) -> str:
    parts = [
        "아래는 오늘 수집된 텔레그램 메시지 JSON 배열입니다. 이 데이터를 분석해 "
        "프롬프트에 정의된 형식대로 한국어 마켓 브리핑을 작성하세요.\n\n"
        "```json\n" + json.dumps(items, ensure_ascii=False, indent=2) + "\n```"
    ]
    if prev_summary:
        parts.append(
            "참고용 — 직전 브리핑의 핵심 요약입니다. 패턴/연속성 분석에만 활용하고, "
            "오늘 데이터에 없는 내용을 사실로 단정하지 마세요:\n\n" + prev_summary
        )
    if focus:
        parts.append(
            f"사용자가 특별히 주목하는 종목/섹터/이슈: {focus}\n"
            "관련 내용이 데이터에 있으면 우선적으로 다뤄주세요."
        )
    return "\n\n---\n\n".join(parts)


def generate_briefing(
    items: list[dict],
    prev_summary: str | None = None,
    focus: str | None = None,
) -> str:
    """브리핑 마크다운 텍스트를 반환. 웹검색을 켜고 pause_turn 을 처리한다."""
    client = anthropic.Anthropic()
    system_prompt = _load_system_prompt()

    messages = [{"role": "user", "content": _build_user_message(items, prev_summary, focus)}]

    response = None
    for _ in range(10):  # 서버측 도구 루프(pause_turn) 안전 상한
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            tools=[WEB_SEARCH_TOOL],
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "pause_turn":
            # 서버측 웹검색 루프가 한도에 도달 — 동일 대화를 다시 보내 이어서 진행.
            messages.append({"role": "assistant", "content": response.content})
            continue
        break

    if response is None:
        raise RuntimeError("Claude 응답을 받지 못했습니다.")

    if response.stop_reason == "refusal":
        raise RuntimeError(
            "Claude 가 안전상의 이유로 응답을 거부했습니다. 입력 데이터를 확인하세요."
        )

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("브리핑 본문이 비어 있습니다 (stop_reason="
                           f"{response.stop_reason}).")
    return text


def summarize_feed(items: list[dict]) -> list[dict]:
    """각 항목의 추출 본문을 2~3문장으로 요약해 item['summary'] 에 채운다.

    본문이 있는 항목만 대상. 구조화 출력(JSON)으로 한 번에 요약. 실패 시 예외를 올리지
    않고 원본 그대로 반환(피드는 추출 본문으로 계속 표시됨)."""
    targets = [(i, it) for i, it in enumerate(items)
               if any(a.get("text") for a in it.get("articles", []))]
    if not targets:
        return items
    payload = []
    for i, it in targets:
        body = "\n".join(a.get("text", "") for a in it["articles"] if a.get("text"))[:3000]
        payload.append({"i": i, "headline": (it.get("text", "") or "")[:120], "body": body})

    client = anthropic.Anthropic()
    schema = {
        "type": "object",
        "properties": {"summaries": {"type": "array", "items": {
            "type": "object",
            "properties": {"i": {"type": "integer"}, "s": {"type": "string"}},
            "required": ["i", "s"], "additionalProperties": False}}},
        "required": ["summaries"], "additionalProperties": False,
    }
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            system=(
                "너는 금융 뉴스/리포트 요약가다. 각 기사를 한국어로 2~3문장, 쉬운 말로 핵심만 "
                "요약하라. 숫자·고유명사는 살리되 군더더기는 빼라. 투자 추천은 하지 마라."
            ),
            messages=[{"role": "user", "content":
                       '아래 기사들을 각각 요약해 JSON 으로만 답하라.\n\n'
                       + json.dumps(payload, ensure_ascii=False)}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        for s in json.loads(text).get("summaries", []):
            idx = s.get("i")
            if isinstance(idx, int) and 0 <= idx < len(items):
                items[idx]["summary"] = s.get("s")
    except Exception as e:  # noqa: BLE001
        print(f"  (피드 요약 건너뜀: {str(e)[:100]})")
    return items
