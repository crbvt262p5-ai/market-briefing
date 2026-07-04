"""수집 피드에서 '그날의 핵심'을 로컬로 추출한다 — Claude/토큰 사용 없음.

아이디어(사용자): 여러 채널에서 반복 언급되는 키워드·정보가 그날의 핵심이다.
따라서 한 채널의 도배가 아니라 **서로 다른 채널 수**를 1차 기준으로 키워드를 랭크한다.
크레딧이 없어 AI 브리핑을 못 만들 때 핵심 브리핑을 이걸로 채운다.
"""
from __future__ import annotations

import re
from collections import defaultdict

# 금융 텍스트에서 흔하지만 '핵심'이 아닌 잡음·보일러플레이트·일반어.
STOP = {
    # 보일러플레이트
    "제목", "이데일리", "이데일리fx", "기자", "리포트", "요약", "브리핑", "코멘트", "뉴스", "속보",
    "특징주", "美특징주", "개장전", "마감", "장중", "전일", "당일", "오늘", "어제", "내일", "금일",
    "데일리", "위클리", "스페셜", "모닝", "morning", "brief", "daily", "weekly", "etf", "fx",
    "the", "and", "for", "with", "inc", "ltd", "www", "com", "co", "kr",
    # 시장 일반어
    "시장", "증시", "증권", "증권사", "종목", "지수", "전망", "예상", "기대", "발표", "공개", "보도",
    "규모", "기록", "확보", "달성", "돌파", "상승", "하락", "강세", "약세", "급등", "급락", "반등",
    "미국", "한국", "국내", "해외", "글로벌", "중국", "유럽", "일본", "뉴욕", "관련", "이번", "지금",
    "대비", "이상", "이하", "가능", "우려", "이슈", "소식", "영향", "전체", "주요", "최대", "최고",
    "계약", "체결", "인수", "발행", "조달", "투자", "매출", "순손실", "순이익", "실적", "가이던스",
    "목표", "의견", "유지", "상향", "하향", "제시", "매수", "매도", "보유", "확대", "축소", "증가",
    "감소", "회복", "둔화", "개선", "악화", "호조", "부진", "전환", "지속", "반영", "포함", "제외",
    # 단위·수량
    "억", "만", "조", "달러", "원", "퍼센트", "포인트", "분기", "연간", "상반기", "하반기", "지난",
    "전년", "올해", "작년", "내년", "가격", "비율", "수준", "정도", "수요", "공급", "성장", "규모",
    # 일반 명사·부사·대명사
    "이후", "이전", "직후", "직전", "현재", "향후", "최근", "다음", "당분간", "이번", "경우", "부분",
    "내용", "상황", "상태", "모습", "측면", "중심", "기준", "결과", "이유", "때문", "사실", "실제",
    "그것", "이것", "저것", "가장", "매우", "아주", "너무", "모든", "일부", "각각", "서로", "함께",
    "대부분", "여전", "특히", "다소", "크게", "점차", "대체", "전반", "지난해", "관계", "가운데",
    "것으", "것은", "것이", "모두", "자금", "대상", "기술", "가능성", "조정", "강화", "생산",
    "요인", "중장기", "단기", "장기", "부담", "수급", "흐름", "전략", "평가", "분석", "예정",
    "계획", "추진", "검토", "논의", "방침", "설명", "언급", "지적", "강조", "확인", "추가",
    "기존", "신규", "대규모", "본격", "점검", "제공", "운영", "적용", "활용", "기반", "중요",
    "이어", "차별화", "변화", "업종",
}

# 조사/접미 — 한국어 토큰 끝에서 떼어낸다.
_JOSA = ("으로써", "으로서", "이라는", "라는", "으로", "에서", "에게", "까지", "부터", "이라", "라고",
         "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "과", "와", "로", "년", "월", "일")


def _strip_josa(tok: str) -> str:
    for j in _JOSA:
        if len(tok) > len(j) + 1 and tok.endswith(j):
            return tok[: -len(j)]
    return tok


# 동사·형용사·서술형 잔여 토큰은 대개 이 글자로 끝난다 — 개체명(기업·테마)은 거의 안 그렇다.
_VERBY_END = ("다", "음", "함", "됨", "임", "게", "며", "면", "고", "서", "했", "됐", "한", "된",
              "는", "던", "라", "야", "죠", "네", "까", "나", "듯", "채", "가", "여", "해")


def _is_verby(tok: str) -> bool:
    return tok.endswith(_VERBY_END)


def keywords_of(text: str) -> set[str]:
    """한 메시지에서 후보 키워드 집합을 뽑는다(중복 제거)."""
    text = re.sub(r"https?://\S+", " ", text)  # URL 제거
    out: set[str] = set()
    # 영문 티커/약어 (2~6자 대문자) 및 일반 영단어
    for m in re.findall(r"[A-Za-z]{2,6}", text):
        low = m.lower()
        if low not in STOP:
            out.add(m.upper() if m.isupper() else low)
    # 한글 토큰 (2자 이상) — 조사 제거 후, 동사/서술형·불용어 제외
    for m in re.findall(r"[가-힣]{2,}", text):
        tok = _strip_josa(m)
        if len(tok) >= 2 and tok not in STOP and not _is_verby(tok):
            out.add(tok)
    return out


def rank_keywords(items: list[dict], top: int = 8) -> list[dict]:
    """(키워드, 채널수, 언급건수, 대표헤드라인) 을 채널수 우선으로 랭크."""
    chans: dict[str, set[str]] = defaultdict(set)  # kw -> 채널 집합
    hits: dict[str, int] = defaultdict(int)        # kw -> 메시지 건수
    head_of: dict[str, str] = {}                    # kw -> 대표 헤드라인
    for it in items:
        text = it.get("text", "") or ""
        ch = it.get("channel", "") or ""
        head = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        for kw in keywords_of(text):
            chans[kw].add(ch)
            hits[kw] += 1
            # 대표 헤드라인은 가장 짧은(=간결한) 걸로
            if kw not in head_of or len(head) < len(head_of[kw]):
                head_of[kw] = head[:90]
    ranked = sorted(
        chans.keys(),
        key=lambda k: (len(chans[k]), hits[k]),
        reverse=True,
    )
    # 채널 2개 이상에서 반복된 것만 '핵심'으로(진짜 반복). 없으면 건수 상위로 폴백.
    core = [k for k in ranked if len(chans[k]) >= 2]
    if len(core) < top:
        core += [k for k in ranked if k not in core]
    return [
        {"kw": k, "channels": len(chans[k]), "hits": hits[k], "head": head_of.get(k, "")}
        for k in core[:top]
    ]


def build_core_markdown(items: list[dict], label: str, top: int = 6) -> str:
    """AI 브리핑이 없을 때 핵심 브리핑을 대신할 마크다운(자동 추출)."""
    kws = rank_keywords(items, top=top)
    lines = [f"## 📊 마켓 브리핑 — {label}", "", "> ⚙️ 자동 추출 요약 (여러 채널에서 반복 언급된 키워드 기준). "
             "AI 종합 브리핑은 크레딧 충전 시 생성됩니다.", "", "### 📌 오늘의 핵심 키워드"]
    if not kws:
        lines.append("- (수집 데이터에서 반복 키워드를 찾지 못했습니다.)")
    for k in kws:
        tag = f"{k['channels']}개 채널·{k['hits']}건"
        head = f" — {k['head']}" if k["head"] else ""
        lines.append(f"- **{k['kw']}** ({tag}){head}")
    lines += ["", "---", "*※ 자동 집계 결과이며 투자 추천이 아닙니다. 원문은 '전체 피드' 참고.*"]
    return "\n".join(lines)
