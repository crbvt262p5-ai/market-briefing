"""링크된 기사/리포트 본문 추출 — 헤드라인이 아니라 실제 내용을 가져온다."""
from __future__ import annotations

import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")  # urllib3/LibreSSL 등 잡경고 숨김

import requests
import trafilatura

URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# 본문이 아닌 링크(텔레그램 내부, 이미지 등)는 추출 대상에서 제외
SKIP_HOST = ("t.me", "telegram.me")


def extract_urls(text: str) -> list[str]:
    urls = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,)]}'\"·  ")
        if any(h in u.split("/")[2] for h in SKIP_HOST):
            continue
        if u not in urls:
            urls.append(u)
    return urls


def fetch_article(url: str, timeout: int = 12, max_chars: int = 4000) -> dict:
    """URL 하나의 본문을 추출. 실패해도 최소한 final_url/kind 는 채워 반환."""
    out = {"url": url, "final_url": url, "title": None, "text": None, "kind": "unknown"}
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA}, allow_redirects=True)
        out["final_url"] = r.url
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" in ctype or r.url.lower().split("?")[0].endswith(".pdf"):
            out["kind"] = "pdf"  # PDF 리포트 — 링크만 제공(본문 추출은 LLM 단계에서)
            return out
        if "html" not in ctype and "text" not in ctype:
            out["kind"] = "other"
            return out
        out["kind"] = "html"
        try:
            md = trafilatura.metadata.extract_metadata(r.text)
            if md and md.title:
                out["title"] = md.title.strip()
        except Exception:
            pass
        text = trafilatura.extract(
            r.text, include_comments=False, include_tables=False, favor_recall=True, url=r.url
        )
        if text:
            text = text.strip()
            out["text"] = (text[:max_chars] + "…") if len(text) > max_chars else text
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:120]
    return out


def fetch_many(urls: list[str], workers: int = 8) -> dict[str, dict]:
    """여러 URL 을 병렬로 추출 → {url: article} 맵."""
    result: dict[str, dict] = {}
    if not urls:
        return result
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_article, u): u for u in urls}
        for f in as_completed(futs):
            u = futs[f]
            try:
                result[u] = f.result()
            except Exception as e:  # noqa: BLE001
                result[u] = {"url": u, "final_url": u, "title": None, "text": None, "kind": "error", "error": str(e)[:120]}
    return result


if __name__ == "__main__":
    import sys

    for u in sys.argv[1:]:
        a = fetch_article(u)
        print(f"\n[{a['kind']}] {a.get('title')}\n{u}\n{(a.get('text') or '(본문 추출 실패)')[:300]}")
