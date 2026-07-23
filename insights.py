"""수집 피드에서 '그날의 핵심'을 로컬로 추출한다 — Claude/토큰 사용 없음.

아이디어(사용자): 여러 채널에서 반복 언급되는 '제네럴한(매크로)' 정보가 그날의 핵심이다.
반대로 키움 해외선물(@kwtok) 등의 미국 소형주 개별뉴스([美특징주] 등)는 노이즈다.
따라서 ① 개별종목 노이즈 아이템은 집계에서 제외하고 ② 매크로 테마를 표기 흔들림까지
정규화해 우선 노출한다. 한 채널 도배가 아니라 **서로 다른 채널 수**를 기준으로 랭크한다.
"""
from __future__ import annotations

import re
from collections import defaultdict

# ── 매크로/제네럴 테마: 표기 변형(부분일치, 소문자) → 대표어 ──────────────────
# 이 테마들은 핵심에서 우선 노출된다. 변형은 lower() 후 부분일치로 탐지.
SYN = {
    "연준": "연준", "fed": "연준", "fomc": "연준", "파월": "연준", "기준금리": "연준",
    "정책금리": "금리", "국채": "금리", "금리": "금리", "수익률": "금리", "일드": "금리", "yield": "금리",
    "환율": "환율", "달러-원": "환율", "달러/원": "환율", "원화": "환율", "달러인덱스": "환율", "dxy": "환율",
    "강달러": "달러", "약달러": "달러", "달러화": "달러",
    "유가": "유가", "wti": "유가", "브렌트": "유가", "원유": "유가",
    "인플레": "인플레이션", "물가": "인플레이션", "cpi": "인플레이션", "pce": "인플레이션", "ppi": "인플레이션",
    "고용": "고용", "실업": "고용", "비농업": "고용", "nfp": "고용", "일자리": "고용",
    "관세": "관세", "무역수지": "관세", "트럼프": "관세",
    "반도체": "반도체", "hbm": "반도체", "d램": "반도체", "디램": "반도체", "낸드": "반도체",
    "파운드리": "반도체", "웨이퍼": "반도체", "메모리": "반도체",
    "인공지능": "AI", " ai ": "AI", "gpu": "AI", "tpu": "AI", "데이터센터": "AI",
    "엔비디아": "엔비디아", "nvidia": "엔비디아", "nvda": "엔비디아",
    "마이크론": "마이크론", "micron": "마이크론",
    "하이닉스": "하이닉스", "sk하이닉스": "하이닉스",
    "삼성전자": "삼성전자", "삼전": "삼성전자",
    "브로드컴": "브로드컴", "broadcom": "브로드컴", "avgo": "브로드컴",
    "amd": "AMD", "테슬라": "테슬라", "tesla": "테슬라", "애플": "애플", "apple": "애플",
    "코스피": "코스피", "kospi": "코스피", "코스닥": "코스피",
    "나스닥": "미국증시", "s&p": "미국증시", "다우": "미국증시", "sox": "미국증시",
    "금값": "금", "골드": "금", "gold": "금",
    "gdp": "경기", "성장률": "경기", "침체": "경기", "연착륙": "경기", "경착륙": "경기",
    "경제지표": "경제지표", "경상수지": "경제지표",
}
MACRO = set(SYN.values())
# '진짜 매크로'(시장 전반 주제). 개별종목 뉴스 구제는 이 집합에만 허용한다 —
# 소형주가 곁다리로 'AI/반도체'를 언급해도 살려주지 않기 위해(섹터테마는 랭킹용).
# '금'·'경기'는 소형주 이름/곁다리 언급과 충돌이 잦아 제외(진짜 금값 뉴스는 금리/연준 동반).
MACRO_STRONG = {"연준", "금리", "환율", "달러", "유가", "인플레이션", "고용", "관세",
                "코스피", "미국증시", "경제지표"}

# 개별종목(소형주) 뉴스 태그 — 이런 아이템은 핵심 집계에서 제외.
_SS_TAGS = ("[美특징주]", "[특징주]", "[개장 전 특징주]", "[개장전 특징주]", "[美 특징주]")

# 금융 텍스트에서 흔하지만 '핵심'이 아닌 잡음·보일러플레이트·일반어.
STOP = {
    "제목", "이데일리", "이데일리fx", "기자", "리포트", "요약", "브리핑", "코멘트", "뉴스", "속보",
    "주식", "정리", "오전", "오후", "일정", "공시",  # 제네릭 — 테마 아님
    "특징주", "美특징주", "개장전", "마감", "장중", "전일", "당일", "오늘", "어제", "내일", "금일",
    "데일리", "위클리", "스페셜", "모닝", "morning", "brief", "daily", "weekly", "etf", "fx",
    "the", "and", "for", "with", "inc", "ltd", "www", "com", "co", "kr",
    "시장", "증시", "증권", "증권사", "종목", "지수", "전망", "예상", "기대", "발표", "공개", "보도",
    "규모", "기록", "확보", "달성", "돌파", "상승", "하락", "강세", "약세", "급등", "급락", "반등",
    "미국", "한국", "국내", "해외", "글로벌", "중국", "유럽", "일본", "뉴욕", "관련", "이번", "지금",
    "대비", "이상", "이하", "가능", "우려", "이슈", "소식", "영향", "전체", "주요", "최대", "최고",
    "계약", "체결", "인수", "발행", "조달", "투자", "매출", "순손실", "순이익", "실적", "가이던스",
    "목표", "의견", "유지", "상향", "하향", "제시", "매수", "매도", "보유", "확대", "축소", "증가",
    "감소", "회복", "둔화", "개선", "악화", "호조", "부진", "전환", "지속", "반영", "포함", "제외",
    "억", "만", "조", "달러", "원", "퍼센트", "포인트", "분기", "연간", "상반기", "하반기", "지난",
    "전년", "올해", "작년", "내년", "가격", "비율", "수준", "정도", "수요", "공급", "성장", "규모",
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

_JOSA = ("으로써", "으로서", "이라는", "라는", "으로", "에서", "에게", "까지", "부터", "이라", "라고",
         "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "과", "와", "로", "년", "월", "일")
_VERBY_END = ("다", "음", "함", "됨", "임", "게", "며", "면", "고", "서", "했", "됐", "한", "된",
              "는", "던", "라", "야", "죠", "네", "까", "나", "듯", "채", "가", "여", "해")


def _strip_josa(tok: str) -> str:
    for j in _JOSA:
        if len(tok) > len(j) + 1 and tok.endswith(j):
            return tok[: -len(j)]
    return tok


def macro_themes(text: str) -> set[str]:
    """텍스트에 등장한 매크로 대표 테마 집합(표기 변형 정규화)."""
    low = " " + text.lower() + " "
    return {canon for syn, canon in SYN.items() if syn in low}


def _head(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def is_single_stock(item: dict) -> bool:
    """키움 해외선물/미국주식 등의 개별 소형주 뉴스면 True(핵심 집계에서 제외).

    - [美특징주]/[특징주] 태그는 개별종목 확정.
    - '톡톡/해외선물' 채널의 '제목 : …' 뉴스 중 매크로 테마가 하나도 없으면 개별종목으로 간주.
    """
    text = item.get("text", "") or ""
    ch = item.get("channel", "") or ""
    head = _head(text)
    # 구제는 '헤드라인'의 진짜 매크로(환율/금리/지표 등)로만 — 본문 곁다리 매크로어는 무시.
    strong = bool(macro_themes(head) & MACRO_STRONG)
    if any(t in text for t in _SS_TAGS):
        return not strong
    if ("톡톡" in ch or "해외선물" in ch) and head.startswith("제목"):
        return not strong
    return False


def _generic_tokens(text: str) -> set[str]:
    """매크로 외 신흥 테마 후보(조사/동사/불용어 제외)."""
    text = re.sub(r"https?://\S+", " ", text)
    out: set[str] = set()
    for m in re.findall(r"[A-Za-z]{2,6}", text):
        low = m.lower()
        if low not in STOP:
            out.add(m.upper() if m.isupper() else low)
    for m in re.findall(r"[가-힣]{2,}", text):
        tok = _strip_josa(m)
        if len(tok) >= 2 and tok not in STOP and not tok.endswith(_VERBY_END):
            out.add(tok)
    return out


def rank_keywords(items: list[dict], top: int = 8) -> list[dict]:
    """(키워드, 채널수, 언급건수, 대표헤드라인)을 매크로 우선·채널수 순으로 랭크.

    개별종목 노이즈 아이템은 제외한다. 매크로 테마는 항상 후보, 신흥 테마는 2개 채널 이상."""
    chans: dict[str, set[str]] = defaultdict(set)
    hits: dict[str, int] = defaultdict(int)
    head_of: dict[str, str] = {}
    for it in items:
        if is_single_stock(it):
            continue
        text = it.get("text", "") or ""
        ch = it.get("channel", "") or ""
        head = _head(text)
        kws = _generic_tokens(text) | macro_themes(text)
        for kw in kws:
            chans[kw].add(ch)
            hits[kw] += 1
            if kw not in head_of or len(head) < len(head_of[kw]):
                head_of[kw] = head[:90]

    def sort_key(k: str):
        return (k in MACRO, len(chans[k]), hits[k])

    ranked = sorted(chans, key=sort_key, reverse=True)
    # 매크로는 무조건 후보. 신흥(비매크로)은 서로 다른 2개 채널 이상에서 반복된 것만.
    core = [k for k in ranked if k in MACRO or len(chans[k]) >= 2]
    if len(core) < top:  # 부족하면 건수 상위로 폴백
        core += [k for k in ranked if k not in core]
    return [
        {"kw": k, "channels": len(chans[k]), "hits": hits[k],
         "macro": k in MACRO, "head": head_of.get(k, "")}
        for k in core[:top]
    ]


def _watch_pattern(term: str) -> re.Pattern:
    # 영문 약어(EV/ESS/BEV 등)는 단어 경계로(REVENUE 같은 단어에 오탐 방지),
    # 한글은 부분일치(조사 결합 "배터리를"에도 매칭).
    if re.fullmatch(r"[A-Za-z]+", term):
        return re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.IGNORECASE)
    return re.compile(re.escape(term))


def match_watchlist(items: list[dict], terms: list[str]) -> dict[str, list[dict]]:
    """items 중 사용자 지정 관심 키워드(배터리/리튬/EV 등)가 헤드라인·요약·본문에
    등장하는 항목만 키워드별로 모은다. 히트 0건인 키워드는 결과에서 제외."""
    pats = {t: _watch_pattern(t) for t in terms}
    out: dict[str, list[dict]] = {t: [] for t in terms}
    for it in items:
        blob = " ".join([
            it.get("text", "") or "",
            it.get("summary", "") or "",
            " ".join((a.get("text") or "") for a in it.get("articles", [])),
        ])
        for t, pat in pats.items():
            if pat.search(blob):
                out[t].append(it)
    return {t: v for t, v in out.items() if v}


def keyword_member_indices(items: list[dict], kws: set[str]) -> dict[str, list[int]]:
    """rank_keywords와 **동일한 판정 기준**(매크로 동의어 정규화 + 신흥 토큰, 텍스트 범위도 동일)으로
    지정된 kws 각각에 실제로 매칭된 items의 인덱스를 모은다 — 대시보드 드릴다운(카드 클릭)이
    막연한 문자열 검색 대신 랭킹을 만든 바로 그 근거로 필터링하도록 하기 위함. 예: 'AI' 키워드는
    본문에 'AI 추천'처럼 단어만 우연히 섞인 글이 아니라, 랭킹 집계에 실제로 기여한 글만 나온다."""
    out: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        if is_single_stock(it):
            continue
        found = (_generic_tokens(it.get("text", "") or "") | macro_themes(it.get("text", "") or "")) & kws
        for kw in found:
            out.setdefault(kw, []).append(i)
    return out


def build_core_markdown(items: list[dict], label: str, top: int = 14) -> str:
    """AI 브리핑이 없을 때 핵심 브리핑을 대신할 마크다운(자동 추출).

    '여러 채널에서 반복'된 키워드일수록 그날의 핵심 — 반복(2개 채널 이상) 테마를
    앞세워 볼륨 있게 나열하고, 그 외 주목 키워드를 뒤에 덧붙인다.
    티저(core_headlines)는 첫 `### 📌` 섹션에서 헤드라인을 뽑으므로 반복 핵심을 📌로 둔다."""
    kws = rank_keywords(items, top=top)
    n_noise = sum(1 for it in items if is_single_stock(it))
    repeated = [k for k in kws if k["channels"] >= 2]
    single = [k for k in kws if k["channels"] < 2]

    def render(k: dict) -> str:
        rep = "🔁 " if k["channels"] >= 2 else ""
        mark = "🌐 " if k["macro"] else ""
        tag = f"{k['channels']}개 채널·{k['hits']}건"
        head = f" — {k['head']}" if k["head"] else ""
        return f"- {rep}{mark}**{k['kw']}** ({tag}){head}"

    lines = [
        f"## 📊 마켓 브리핑 — {label}", "",
        "> ⚙️ 자동 추출 요약 — 여러 채널이 함께 다룰수록(반복도) 상위. "
        f"개별 소형주 뉴스 {n_noise}건은 집계 제외. (AI 종합 브리핑은 크레딧 충전 시)", "",
    ]
    if not kws:
        lines += ["### 📌 오늘의 핵심", "- (수집 데이터에서 반복 테마를 찾지 못했습니다.)"]
    else:
        if repeated:
            lines.append(f"### 📌 반복 핵심 — 여러 채널이 함께 다룬 테마 ({len(repeated)})")
            lines += [render(k) for k in repeated]
        # 반복 테마가 없으면 '그 외'를 📌로 승격해 티저가 빈손이 되지 않게 한다.
        heading = "🧩 그 외 주목 키워드" if repeated else "📌 오늘의 주목 키워드"
        if single:
            lines += ["", f"### {heading} ({len(single)})"]
            lines += [render(k) for k in single]
    lines += ["", "---", "*※ 자동 집계 결과이며 투자 추천이 아닙니다. 원문은 '전체 피드' 참고.*"]
    return "\n".join(lines)
