# 데일리 마켓 브리핑

텔레그램 애널리스트/뉴스 채널을 매일 수집해 Claude 가 종합 분석하고,
결과 브리핑을 다시 텔레그램(본인 Saved Messages)으로 보내주는 파이프라인.

```
collect.py  →  generate.py  →  deliver.py
 (Telethon)    (Claude API)     (Telethon)
   수집           분석·작성        전달
        └──────── run_daily.py ────────┘
```

- **수집**: Telethon 사용자 세션으로 구독 채널의 최근 24시간 메시지 수집
- **생성**: `claude-opus-4-8` + 웹검색(`web_search_20260209`)으로 `prompt.md` 형식대로 한국어 브리핑 작성
- **전달**: 본인 텔레그램 Saved Messages 로 전송 (4096자 자동 분할)

## 1. 설치

```bash
cd ~/market-briefing
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 자격증명 설정

```bash
cp .env.example .env
```

`.env` 를 열어 채웁니다:

- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — https://my.telegram.org → *API development tools* 에서 발급
- `ANTHROPIC_API_KEY` — https://platform.claude.com 에서 발급

그다음 텔레그램 세션 문자열을 1회 생성합니다 (전화번호·인증코드 입력):

```bash
python login.py
```

출력된 긴 문자열을 `.env` 의 `TELEGRAM_SESSION=` 에 붙여넣습니다. 이후로는 재로그인 불필요.

> 세션 입력이 인터랙티브하므로, Claude Code 안에서라면 프롬프트에 `! python login.py` 로 직접 실행하세요.

## 3. 채널 설정

`config.yaml` 의 `channels:` 에 모니터할 채널(`@username` 또는 `t.me` 링크)을 나열합니다.
비공개 채널은 본인 계정이 **구독(가입)** 되어 있어야 읽을 수 있습니다.

```yaml
channels:
  - "@analyst_one"
  - "@market_news_kr"
lookback_hours: 24
deliver_to: "me"        # 본인 Saved Messages
focus: ""               # 특별히 주목할 종목/섹터 (선택)
```

## 4. 실행

```bash
python run_daily.py                 # 수집 → 생성 → 전달 (전체)
python run_daily.py --no-deliver    # 파일만 생성, 전송 생략 (테스트용)
python run_daily.py --raw briefings/raw_2026-06-20.json   # 기존 수집본으로 생성만
```

결과물:
- `briefings/raw_YYYY-MM-DD.json` — 수집 원본
- `briefings/briefing_YYYY-MM-DD.md` — 생성된 브리핑

직전 브리핑의 TL;DR 은 다음 실행 시 자동으로 맥락으로 전달되어 패턴 분석의 연속성을 더합니다.

## 5. 매일 자동 실행 (cron)

매일 오전 7시에 돌리는 예 (가상환경 파이썬 절대경로 사용):

```cron
0 7 * * *  cd /Users/taeheehong/market-briefing && /Users/taeheehong/market-briefing/.venv/bin/python run_daily.py >> briefings/cron.log 2>&1
```

`crontab -e` 로 위 줄을 추가하세요. macOS 에서는 cron 이 디스크/네트워크 접근 권한을 요구할 수 있으니,
처음 한 번은 수동 실행으로 권한을 허용해 두는 것이 안전합니다.

## 동작 메모

- 웹 검색은 텔레그램 원문에 수치/배경이 부족할 때 Claude 가 자동으로 호출하며, 보강 내용은 브리핑에서 `[검색 보강]` 으로 표시됩니다.
- 투자 추천/단정은 하지 않도록 프롬프트에 명시돼 있습니다 (정보·맥락 정리 목적).
- 텔레그램 전송은 평문(parse_mode 없음)으로 보내 마크다운 기호를 그대로 노출합니다 — 엔티티 파싱 오류를 피하기 위함입니다.
