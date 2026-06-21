"""텔레그램 StringSession 1회 생성기.

실행:  python login.py
전화번호 → 인증코드(→ 2단계 비밀번호) 입력 후 출력되는 문자열을
.env 의 TELEGRAM_SESSION 에 붙여넣으세요. 세션은 재사용되므로 매번 로그인할 필요가 없습니다.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

load_dotenv()


def main() -> None:
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit(
            "먼저 .env 에 TELEGRAM_API_ID / TELEGRAM_API_HASH 를 채우세요 "
            "(my.telegram.org 에서 발급)."
        )

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        session_str = client.session.save()
        me = client.get_me()
        print("\n로그인 성공:", me.first_name, f"(@{me.username})" if me.username else "")
        print("\n아래 문자열을 .env 의 TELEGRAM_SESSION 값으로 붙여넣으세요:\n")
        print(session_str)
        print()


if __name__ == "__main__":
    main()
