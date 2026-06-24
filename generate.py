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


# 메시지 본문 자체가 충분히 길면(링크 없이도) 요약 대상으로 본다 — 키움 해외선물처럼
# 뉴스 전문이 텍스트에 담기는 채널 대응.
TEXT_SUMMARY_MIN = 200
# 한 번에 요약할 최대 항목 수(밤사이 누적 시 토큰·비용 폭주 방지). 최신순 우선.
MAX_SUMMARIZE = 80
# 한 요청당 요약 항목 수. 너무 많으면 출력 JSON 이 max_tokens 에 잘려 파싱 실패하므로 분할.
SUMMARIZE_BATCH = 15

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summaries": {"type": "array", "items": {
        "type": "object",
        "properties": {"i": {"type": "integer"}, "s": {"type": "string"}},
        "required": ["i", "s"], "additionalProperties": False}}},
    "required": ["summaries"], "additionalProperties": False,
}
_SUMMARY_SYSTEM = (
    "너는 금융 뉴스/리포트 요약가다. 각 기사를 한국어로 2~3문장, 쉬운 말로 핵심만 "
    "요약하라. 숫자·고유명사는 살리되 군더더기는 빼라. 투자 추천은 하지 마라."
)


def _summary_body(it: dict) -> str | None:
    """요약에 쓸 본문을 고른다: 추출 기사 본문 우선, 없으면 충분히 긴 메시지 텍스트."""
    arts = "\n".join(a.get("text", "") for a in it.get("articles", []) if a.get("text"))
    if arts.strip():
        return arts[:3000]
    text = (it.get("text", "") or "").strip()
    if len(text) >= TEXT_SUMMARY_MIN:
        return text[:3000]
    return None


def _summarize_batch(client, payload: list[dict], items: list[dict]) -> int:
    """payload 한 묶음을 요약해 items[idx]['summary'] 에 채운다. 채운 개수 반환."""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        output_config={"format": {"type": "json_schema", "schema": _SUMMARY_SCHEMA}},
        system=_SUMMARY_SYSTEM,
        messages=[{"role": "user", "content":
                   '아래 기사들을 각각 요약해 JSON 으로만 답하라.\n\n'
                   + json.dumps(payload, ensure_ascii=False)}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    n = 0
    for s in json.loads(text).get("summaries", []):
        idx = s.get("i")
        if isinstance(idx, int) and 0 <= idx < len(items):
            items[idx]["summary"] = s.get("s")
            n += 1
    return n


def summarize_feed(items: list[dict]) -> list[dict]:
    """각 항목을 2~3문장으로 요약해 item['summary'] 에 채운다.

    링크 기사 본문이 있는 항목 + 본문이 긴 텍스트 메시지(키움 해외선물 등)를 모두 대상으로
    한다. 항목이 많으면 출력 JSON 이 잘리지 않도록 배치로 나눠 요청한다. 배치 단위로
    best-effort — 일부 배치가 실패해도 나머지는 요약된다."""
    cand = [(i, it, _summary_body(it)) for i, it in enumerate(items)]
    cand = [(i, it, b) for i, it, b in cand if b]
    if not cand:
        return items
    # 항목이 많으면 최신(뒤쪽) 우선으로 상한 적용
    targets = cand[-MAX_SUMMARIZE:] if len(cand) > MAX_SUMMARIZE else cand
    payload = [{"i": i, "headline": (it.get("text", "") or "")[:120], "body": body}
               for i, it, body in targets]

    client = anthropic.Anthropic()
    done = 0
    for start in range(0, len(payload), SUMMARIZE_BATCH):
        batch = payload[start:start + SUMMARIZE_BATCH]
        try:
            done += _summarize_batch(client, batch, items)
        except Exception as e:  # noqa: BLE001
            print(f"  (요약 배치 {start // SUMMARIZE_BATCH + 1} 건너뜀: {str(e)[:100]})")
    print(f"  피드 요약 완료: {done}/{len(payload)}건")
    return items
