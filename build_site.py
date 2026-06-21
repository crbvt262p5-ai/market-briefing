"""정적 대시보드 빌더 — 브리핑을 비밀번호로 암호화해 docs/index.html 생성.

보안 설계: GitHub Pages 무료 호스팅은 공개 저장소를 쓰므로, 브리핑 '원문(.md)'은
저장소에 절대 커밋하지 않는다(.gitignore). 대신 본문을 AES-GCM 으로 암호화한
docs/index.html 만 커밋한다 → 저장소를 봐도, 소스를 봐도 비번 없이는 내용을 못 본다.

과거 브리핑 누적: 빌드 시 기존 docs/index.html 의 암호문을 SITE_PASSWORD 로
복호화해 과거분을 읽고, 이번에 새로 생성된 briefings/*.md 를 합쳐 다시 암호화한다.
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent
BRIEFINGS = ROOT / "briefings"
DOCS = ROOT / "docs"
ITERATIONS = 200_000


def _derive(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(
        password.encode("utf-8")
    )


def encrypt(plaintext: str, password: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_derive(password, salt)).encrypt(iv, plaintext.encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "iter": ITERATIONS}


def decrypt(payload: dict, password: str) -> str:
    d = base64.b64decode
    key = _derive(password, d(payload["salt"]))
    return AESGCM(key).decrypt(d(payload["iv"]), d(payload["ct"]), None).decode("utf-8")


def local_briefings() -> list[dict]:
    """이번 실행 워크스페이스에 있는 briefing_*.md (이번에 생성된 신규 포함)."""
    out = []
    for p in sorted(BRIEFINGS.glob("briefing_*.md"), reverse=True):
        m = re.match(r"briefing_(\d{4}-\d{2}-\d{2})\.md", p.name)
        if m:
            out.append({"date": m.group(1), "markdown": p.read_text(encoding="utf-8")})
    return out


def prior_briefings(password: str) -> list[dict]:
    """기존 docs/index.html 의 암호문을 복호화해 과거 브리핑을 복원."""
    idx = DOCS / "index.html"
    if not idx.exists():
        return []
    m = re.search(r'id="payload" type="application/json">(.*?)</script>', idx.read_text(encoding="utf-8"), re.S)
    if not m:
        return []
    try:
        return json.loads(decrypt(json.loads(m.group(1)), password)).get("briefings", [])
    except Exception:
        print("경고: 기존 사이트 복호화 실패(비번 변경?) — 과거분 없이 새로 시작")
        return []


HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>데일리 마켓 브리핑</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --fg:#e6e9ef; --muted:#9aa4b2; --accent:#5b9dff; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Segoe UI",sans-serif;
         background:var(--bg); color:var(--fg); }
  header { padding:14px 20px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:14px;
           position:sticky; top:0; background:var(--bg); z-index:5; flex-wrap:wrap; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  select, button, input { background:var(--panel); color:var(--fg); border:1px solid var(--line);
           border-radius:8px; padding:8px 12px; font-size:14px; }
  button { cursor:pointer; }
  .gate { max-width:360px; margin:18vh auto 0; padding:28px; background:var(--panel);
          border:1px solid var(--line); border-radius:14px; text-align:center; }
  .gate h2 { font-size:18px; margin:0 0 6px; }
  .gate p { color:var(--muted); font-size:13px; margin:0 0 18px; }
  .gate input { width:100%; margin-bottom:10px; }
  .gate button { width:100%; background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
  .gate .err { color:#ff6b6b; font-size:13px; height:18px; }
  .wrap { max-width:880px; margin:0 auto; padding:24px 22px 60px; }
  .md { font-size:15px; line-height:1.75; }
  .md h3 { margin-top:28px; padding-bottom:6px; border-bottom:1px solid var(--line); font-size:18px; }
  .md h1,.md h2 { font-size:20px; }
  .md blockquote { border-left:3px solid var(--accent); margin:0 0 18px; padding:10px 14px; background:var(--panel);
                   border-radius:0 8px 8px 0; color:var(--muted); font-size:13.5px; }
  .md code { background:var(--panel); padding:1px 5px; border-radius:4px; font-size:13px; }
  .md a { color:var(--accent); word-break:break-all; }
  .md ul { padding-left:20px; } .md li { margin:5px 0; }
  .md hr { border:0; border-top:1px solid var(--line); margin:22px 0; }
  .hidden { display:none; }
  .foot { color:var(--muted); font-size:12px; text-align:center; margin-top:30px; }
</style>
</head>
<body>
<div id="gate" class="gate">
  <h2>📰 데일리 마켓 브리핑</h2>
  <p>비밀번호를 입력하세요</p>
  <input id="pw" type="password" placeholder="비밀번호" autocomplete="current-password">
  <button id="go">열기</button>
  <div class="err" id="err"></div>
</div>

<div id="app" class="hidden">
  <header>
    <h1>📰 데일리 마켓 브리핑</h1>
    <select id="dateSel"></select>
    <span id="updated" style="color:var(--muted);font-size:12px"></span>
  </header>
  <div class="wrap"><div class="md" id="briefing"></div>
    <div class="foot">GitHub Actions 자동 생성 · GitHub Pages 호스팅</div>
  </div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const payload = JSON.parse(document.getElementById('payload').textContent);
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function decrypt(pw) {
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey('raw', enc.encode(pw), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    {name:'PBKDF2', salt:b64(payload.salt), iterations:payload.iter, hash:'SHA-256'},
    base, {name:'AES-GCM', length:256}, false, ['decrypt']);
  const plain = await crypto.subtle.decrypt({name:'AES-GCM', iv:b64(payload.iv)}, key, b64(payload.ct));
  return JSON.parse(new TextDecoder().decode(plain));
}
let DATA = null;
function render(date) {
  const b = DATA.briefings.find(x => x.date === date);
  document.getElementById('briefing').innerHTML = marked.parse(b ? b.markdown : '');
}
async function unlock() {
  const pw = document.getElementById('pw').value;
  try { DATA = await decrypt(pw); }
  catch (e) { document.getElementById('err').textContent = '비밀번호가 틀렸습니다'; return; }
  sessionStorage.setItem('mb_pw', pw);
  document.getElementById('gate').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  const sel = document.getElementById('dateSel');
  sel.innerHTML = '';
  DATA.briefings.forEach(b => { const o=document.createElement('option'); o.value=b.date; o.textContent=b.date; sel.appendChild(o); });
  sel.onchange = () => render(sel.value);
  document.getElementById('updated').textContent = '업데이트: ' + (DATA.meta.built_at || '');
  if (DATA.briefings.length) render(DATA.briefings[0].date);
}
document.getElementById('go').onclick = unlock;
document.getElementById('pw').addEventListener('keydown', e => { if (e.key === 'Enter') unlock(); });
const saved = sessionStorage.getItem('mb_pw');
if (saved) { document.getElementById('pw').value = saved; unlock(); }
</script>
</body>
</html>"""


def main() -> None:
    password = os.environ.get("SITE_PASSWORD")
    if not password:
        raise SystemExit("환경변수 SITE_PASSWORD 가 필요합니다 (대시보드 비밀번호).")

    by_date = {b["date"]: b for b in prior_briefings(password)}
    for b in local_briefings():  # 이번 실행에서 새로 생성된 분이 우선
        by_date[b["date"]] = b
    briefings = sorted(by_date.values(), key=lambda b: b["date"], reverse=True)

    plain = json.dumps(
        {"meta": {"built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}, "briefings": briefings},
        ensure_ascii=False,
    )
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(HTML.replace("__PAYLOAD__", json.dumps(encrypt(plain, password))), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"docs/index.html 생성 완료 (브리핑 {len(briefings)}건, 암호화됨)")


if __name__ == "__main__":
    main()
