"""정적 대시보드 빌더 — 비밀번호로 암호화한 docs/index.html 생성.

대시보드 = ① 핵심 브리핑(짧은 요약) + ② 전체 피드(수집된 모든 기사/리포트를
본문과 함께 나열, 골라보기). 밝은 테마.

보안: 공개 저장소엔 '암호화된' docs/index.html 만 커밋한다. 원문(.md)·수집데이터
(raw_*.json)는 절대 커밋하지 않는다(.gitignore). 과거분은 기존 암호문을
SITE_PASSWORD 로 복호화해 누적한다.
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


def local_briefings() -> dict[str, str]:
    out = {}
    for p in sorted(BRIEFINGS.glob("briefing_*.md")):
        m = re.match(r"briefing_(\d{4}-\d{2}-\d{2})\.md", p.name)
        if m:
            out[m.group(1)] = p.read_text(encoding="utf-8")
    return out


def local_feeds() -> dict[str, list]:
    feeds: dict[str, list] = {}
    for p in sorted(BRIEFINGS.glob("raw_*.json")):
        m = re.match(r"raw_(\d{4}-\d{2}-\d{2})\.json", p.name)
        if not m:
            continue
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        feed = []
        for it in items:
            head = next((ln for ln in (it.get("text", "") or "").splitlines() if ln.strip()), "")
            arts = []
            for a in it.get("articles", []):
                if a.get("text") or a.get("kind") == "pdf":
                    arts.append(
                        {
                            "title": a.get("title"),
                            "text": (a.get("text") or "")[:1200],
                            "url": a.get("final_url") or a.get("url"),
                            "kind": a.get("kind"),
                        }
                    )
            feed.append(
                {
                    "ch": it.get("channel"),
                    "ts": it.get("timestamp"),
                    "head": head[:240],
                    "tlink": it.get("link"),
                    "summary": it.get("summary"),
                    "arts": arts,
                }
            )
        feeds[m.group(1)] = feed
    return feeds


def prior_payload(password: str) -> dict:
    idx = DOCS / "index.html"
    if not idx.exists():
        return {"briefings": {}, "feeds": {}}
    m = re.search(r'id="payload" type="application/json">(.*?)</script>', idx.read_text(encoding="utf-8"), re.S)
    if not m:
        return {"briefings": {}, "feeds": {}}
    try:
        data = json.loads(decrypt(json.loads(m.group(1)), password))
        b = data.get("briefings", {})
        if isinstance(b, list):  # 구버전 포맷(list) 호환
            b = {x["date"]: x["markdown"] for x in b if isinstance(x, dict) and "date" in x}
        f = data.get("feeds", {})
        return {"briefings": b if isinstance(b, dict) else {}, "feeds": f if isinstance(f, dict) else {}}
    except Exception:
        print("경고: 기존 사이트 복호화 실패(비번 변경?) — 과거분 없이 새로 시작")
        return {"briefings": {}, "feeds": {}}


HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>데일리 마켓 브리핑</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root{
    --bg:#f4f6f9; --card:#ffffff; --line:#e6e9ef; --fg:#1f2533; --muted:#6b7686;
    --accent:#2563eb; --accent-soft:#eaf1ff; --chip:#eef1f6;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--fg);
    font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;}
  a{color:var(--accent);text-decoration:none;} a:hover{text-decoration:underline;}
  header{position:sticky;top:0;z-index:10;background:rgba(244,246,249,.92);backdrop-filter:blur(8px);
    border-bottom:1px solid var(--line);padding:12px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;}
  header h1{font-size:16px;margin:0;font-weight:700;letter-spacing:-.01em;}
  .tabs{display:flex;gap:6px;background:var(--chip);padding:4px;border-radius:10px;}
  .tab{border:0;background:transparent;color:var(--muted);font-size:14px;font-weight:600;
    padding:7px 14px;border-radius:7px;cursor:pointer;}
  .tab.active{background:var(--card);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.08);}
  select,input{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:9px;
    padding:8px 11px;font-size:14px;}
  input::placeholder{color:#9aa3b0;}
  .spacer{flex:1;}
  .wrap{max-width:860px;margin:0 auto;padding:22px 18px 70px;}

  /* 브리핑 */
  .md{font-size:15.5px;line-height:1.78;}
  .md h3{margin:30px 0 8px;font-size:17px;font-weight:700;color:#111827;}
  .md h1,.md h2{font-size:19px;}
  .md blockquote{border-left:3px solid var(--accent);margin:0 0 16px;padding:10px 14px;
    background:var(--accent-soft);border-radius:0 10px 10px 0;color:#3a4658;font-size:13.5px;}
  .md ul{padding-left:20px;} .md li{margin:5px 0;}
  .md code{background:#eef1f6;padding:1px 6px;border-radius:5px;font-size:13px;}
  .md a{word-break:break-all;}
  .md hr{border:0;border-top:1px solid var(--line);margin:22px 0;}

  /* 피드 */
  .feedbar{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;}
  .feedbar input{flex:1;min-width:160px;}
  .meta{color:var(--muted);font-size:13px;margin:2px 0 14px;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px;
    margin-bottom:12px;box-shadow:0 1px 2px rgba(16,24,40,.04);}
  .card .top{display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:7px;}
  .chip{background:var(--accent-soft);color:var(--accent);font-size:12px;font-weight:700;
    padding:3px 9px;border-radius:999px;white-space:nowrap;}
  .time{color:var(--muted);font-size:12px;white-space:nowrap;}
  .head{font-size:15.5px;font-weight:600;line-height:1.45;margin:2px 0 6px;color:#111827;}
  .summary{font-size:14px;line-height:1.65;color:#283142;background:#f8fafc;border:1px solid var(--line);
    border-radius:10px;padding:10px 12px;margin:8px 0;}
  .summary b{color:var(--accent);}
  .art{margin-top:8px;border-top:1px dashed var(--line);padding-top:8px;}
  .art .at{font-size:13.5px;font-weight:600;margin-bottom:3px;}
  .art .body{font-size:13.5px;line-height:1.62;color:#3a4250;white-space:pre-wrap;
    max-height:84px;overflow:hidden;position:relative;}
  .art .body.open{max-height:none;}
  .art .fade{position:absolute;bottom:0;left:0;right:0;height:30px;
    background:linear-gradient(transparent,var(--card));}
  .art .toggle{font-size:12.5px;color:var(--accent);cursor:pointer;margin-top:5px;display:inline-block;}
  .links{margin-top:9px;display:flex;gap:8px;flex-wrap:wrap;}
  .links a{font-size:12.5px;background:var(--chip);padding:5px 11px;border-radius:8px;color:#374151;}
  .links a:hover{background:#e2e7ef;text-decoration:none;}
  .badge{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:2px 6px;}
  .hidden{display:none;}
  .foot{color:var(--muted);font-size:12px;text-align:center;margin-top:34px;}

  /* 잠금 */
  .gate{max-width:360px;margin:16vh auto 0;padding:30px;background:var(--card);border:1px solid var(--line);
    border-radius:16px;text-align:center;box-shadow:0 4px 24px rgba(16,24,40,.06);}
  .gate h2{font-size:19px;margin:0 0 6px;} .gate p{color:var(--muted);font-size:13px;margin:0 0 18px;}
  .gate input{width:100%;margin-bottom:10px;}
  .gate button{width:100%;background:var(--accent);border:0;color:#fff;font-weight:700;
    padding:11px;border-radius:9px;cursor:pointer;font-size:14px;}
  .gate .err{color:#dc2626;font-size:13px;height:18px;margin-top:6px;}
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
    <h1>📰 마켓 브리핑</h1>
    <div class="tabs">
      <button class="tab active" data-view="brief">핵심 브리핑</button>
      <button class="tab" data-view="feed">전체 피드</button>
    </div>
    <div class="spacer"></div>
    <select id="dateSel"></select>
    <button class="tab" id="logout" title="이 기기에서 비밀번호 기억 지우기">로그아웃</button>
  </header>
  <div class="wrap">
    <div id="brief" class="md"></div>
    <div id="feed" class="hidden">
      <div class="feedbar">
        <select id="chSel"></select>
        <input id="q" placeholder="검색 (제목·본문)">
      </div>
      <div class="meta" id="feedMeta"></div>
      <div id="cards"></div>
    </div>
    <div class="foot">GitHub Actions 자동 수집·생성 · 본문 추출 포함</div>
  </div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const payload = JSON.parse(document.getElementById('payload').textContent);
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const esc = s => (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function decrypt(pw){
  const enc=new TextEncoder();
  const base=await crypto.subtle.importKey('raw',enc.encode(pw),'PBKDF2',false,['deriveKey']);
  const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt:b64(payload.salt),iterations:payload.iter,hash:'SHA-256'},
    base,{name:'AES-GCM',length:256},false,['decrypt']);
  const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(payload.iv)},key,b64(payload.ct));
  return JSON.parse(new TextDecoder().decode(plain));
}
let DATA=null, CUR=null, VIEW='brief';

function dates(){ return Object.keys(DATA.briefings||{}).concat(Object.keys(DATA.feeds||{}))
  .filter((v,i,a)=>a.indexOf(v)===i).sort().reverse(); }

function renderBrief(){
  const md=(DATA.briefings||{})[CUR]||'_이 날짜의 브리핑이 아직 없습니다. (생성 단계는 크레딧 필요)_';
  document.getElementById('brief').innerHTML=marked.parse(md);
}
function renderFeed(){
  const feed=(DATA.feeds||{})[CUR]||[];
  const chSel=document.getElementById('chSel');
  const chs=[...new Set(feed.map(x=>x.ch))];
  if(chSel.dataset.date!==CUR){
    chSel.innerHTML='<option value="">전체 채널 ('+feed.length+')</option>'+
      chs.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
    chSel.dataset.date=CUR;
  }
  const ch=chSel.value, q=document.getElementById('q').value.trim().toLowerCase();
  let rows=feed.slice().reverse();
  if(ch) rows=rows.filter(r=>r.ch===ch);
  if(q) rows=rows.filter(r=>JSON.stringify(r).toLowerCase().includes(q));
  document.getElementById('feedMeta').textContent=`${rows.length}건`;
  document.getElementById('cards').innerHTML=rows.map(card).join('') ||
    '<div class="meta">표시할 항목이 없습니다.</div>';
}
function card(r){
  const t=(r.ts||'').replace('T',' ').slice(5,16);
  const sum=r.summary?`<div class="summary">${esc(r.summary)}</div>`:'';
  const arts=(r.arts||[]).map(a=>{
    if(a.kind==='pdf') return `<div class="art"><span class="badge">PDF 리포트</span> <a href="${esc(a.url)}" target="_blank">원문 열기 ↗</a></div>`;
    if(!a.text) return '';
    return `<div class="art">${a.title?`<div class="at">${esc(a.title)}</div>`:''}
      <div class="body">${esc(a.text)}<div class="fade"></div></div>
      <span class="toggle" onclick="const b=this.previousElementSibling;b.classList.toggle('open');this.textContent=b.classList.contains('open')?'접기':'본문 더보기';">본문 더보기</span></div>`;
  }).join('');
  const links=[];
  if(r.tlink) links.push(`<a href="${esc(r.tlink)}" target="_blank">텔레그램 ↗</a>`);
  (r.arts||[]).forEach((a,i)=>{ if(a.url) links.push(`<a href="${esc(a.url)}" target="_blank">원문${(r.arts.length>1)?(i+1):''} ↗</a>`); });
  return `<div class="card"><div class="top"><span class="chip">${esc(r.ch)}</span><span class="time">${t}</span></div>
    <div class="head">${esc(r.head)}</div>${sum}${arts}<div class="links">${links.join('')}</div></div>`;
}
function render(){ VIEW==='brief'?renderBrief():renderFeed(); }

function setView(v){ VIEW=v;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.view===v));
  document.getElementById('brief').classList.toggle('hidden',v!=='brief');
  document.getElementById('feed').classList.toggle('hidden',v!=='feed');
  render();
}
async function unlock(){
  const pw=document.getElementById('pw').value;
  try{ DATA=await decrypt(pw); }catch(e){ document.getElementById('err').textContent='비밀번호가 틀렸습니다'; return; }
  localStorage.setItem('mb_pw',pw);   // 이 기기에 기억(브라우저 닫아도 유지)
  document.getElementById('gate').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  const sel=document.getElementById('dateSel');
  const ds=dates(); sel.innerHTML=ds.map(d=>`<option>${d}</option>`).join('');
  CUR=ds[0]; sel.onchange=()=>{CUR=sel.value;render();};
  document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>setView(t.dataset.view));
  document.getElementById('chSel').onchange=renderFeed;
  document.getElementById('q').oninput=renderFeed;
  document.getElementById('logout').onclick=()=>{localStorage.removeItem('mb_pw');location.reload();};
  setView('brief');
}
document.getElementById('go').onclick=unlock;
document.getElementById('pw').addEventListener('keydown',e=>{if(e.key==='Enter')unlock();});
// 링크에 #pw=... 가 있으면 자동 잠금해제(텔레그램에서 탭 한 번에 열림). 주소창에선 즉시 제거.
let hpw=null;
if(location.hash.indexOf('pw=')>=0){ try{hpw=decodeURIComponent(location.hash.split('pw=')[1].split('&')[0]);}catch(e){} }
const saved=hpw||localStorage.getItem('mb_pw');
if(saved){ document.getElementById('pw').value=saved; if(hpw) history.replaceState(null,'',location.pathname); unlock(); }
</script>
</body>
</html>"""


def main() -> None:
    password = os.environ.get("SITE_PASSWORD")
    if not password:
        raise SystemExit("환경변수 SITE_PASSWORD 가 필요합니다 (대시보드 비밀번호).")

    prior = prior_payload(password)
    briefings = dict(prior["briefings"]); briefings.update(local_briefings())
    feeds = dict(prior["feeds"]); feeds.update(local_feeds())

    plain = json.dumps(
        {"meta": {"built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")},
         "briefings": briefings, "feeds": feeds},
        ensure_ascii=False,
    )
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(HTML.replace("__PAYLOAD__", json.dumps(encrypt(plain, password))), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"docs/index.html 생성 (브리핑 {len(briefings)}일 · 피드 {sum(len(v) for v in feeds.values())}건, 암호화됨)")


if __name__ == "__main__":
    main()
