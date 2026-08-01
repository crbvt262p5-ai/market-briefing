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

import config
from insights import is_single_stock, keyword_member_indices, match_watchlist, rank_keywords

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
    # 키 = 날짜 또는 날짜_슬롯(예: 2026-06-24 / 2026-06-24_17)
    out = {}
    for p in sorted(BRIEFINGS.glob("briefing_*.md")):
        m = re.match(r"briefing_(\d{4}-\d{2}-\d{2}(?:_\d{2})?)\.md", p.name)
        if m:
            out[m.group(1)] = p.read_text(encoding="utf-8")
    return out


def _feed_row(it: dict) -> dict:
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
    return {
        "ch": it.get("channel"),
        "ts": it.get("timestamp"),
        "head": head[:240],
        "tlink": it.get("link"),
        "summary": it.get("summary"),
        "arts": arts,
        "ss": 1 if is_single_stock(it) else 0,  # 개별 소형주 노이즈(기본 숨김)
    }


def _dated_raw_items():
    """raw_*.json 을 (날짜/슬롯 키, items) 쌍으로 yield — 파싱 실패는 건너뜀."""
    for p in sorted(BRIEFINGS.glob("raw_*.json")):
        m = re.match(r"raw_(\d{4}-\d{2}-\d{2}(?:_\d{2})?)\.json", p.name)
        if not m:
            continue
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        yield m.group(1), items


def local_feeds() -> dict[str, list]:
    return {key: [_feed_row(it) for it in items] for key, items in _dated_raw_items()}


def local_keywords() -> dict[str, dict]:
    """raw_*.json 에서 '여러 채널이 함께 다룬 반복 키워드 = 그날의 핵심'을 구조화해 뽑는다.

    대시보드가 이 구조를 카드/칩으로 시각화한다(가독성·대표성). rank_keywords 재사용 —
    랭킹 로직은 insights.py 한 곳에만 둔다."""
    out: dict[str, dict] = {}
    for key, items in _dated_raw_items():
        kws = rank_keywords(items, top=18)
        out[key] = {
            "kws": kws,
            "n_noise": sum(1 for it in items if is_single_stock(it)),
            "n_items": len(items),
            # 카드 클릭 드릴다운이 랭킹을 만든 근거(헤드라인 텍스트)로만 필터하도록 —
            # 스크랩된 기사 본문의 사이트 위젯 잡음("AI 추천 뉴스" 등)에 낚이지 않게.
            "idx": keyword_member_indices(items, {k["kw"] for k in kws}),
        }
    return out


def local_watchlist() -> dict[str, dict]:
    """raw_*.json 에서 config.yaml 의 watch_terms(배터리/리튬/EV 등 지정 키워드)가
    언급된 항목의 **인덱스**를 날짜별·키워드별로 모은다(feeds[date]와 같은 순서 —
    카드를 따로 안 실어 대시보드가 클릭 시 정확히 드릴다운하게). 히트 없는 날짜/키워드는 생략."""
    terms = config.watch_terms()
    if not terms:
        return {}
    out: dict[str, dict] = {}
    for key, items in _dated_raw_items():
        matched = match_watchlist(items, terms)
        if matched:
            out[key] = matched
    return out


def prior_payload(password: str) -> dict:
    empty = {"briefings": {}, "feeds": {}, "keywords": {}, "watchlist": {}}
    idx = DOCS / "index.html"
    if not idx.exists():
        return dict(empty)
    m = re.search(r'id="payload" type="application/json">(.*?)</script>', idx.read_text(encoding="utf-8"), re.S)
    if not m:
        return dict(empty)
    try:
        data = json.loads(decrypt(json.loads(m.group(1)), password))
        b = data.get("briefings", {})
        if isinstance(b, list):  # 구버전 포맷(list) 호환
            b = {x["date"]: x["markdown"] for x in b if isinstance(x, dict) and "date" in x}
        f = data.get("feeds", {})
        k = data.get("keywords", {})
        w = data.get("watchlist", {})
        return {"briefings": b if isinstance(b, dict) else {},
                "feeds": f if isinstance(f, dict) else {},
                "keywords": k if isinstance(k, dict) else {},
                "watchlist": w if isinstance(w, dict) else {}}
    except Exception:
        print("경고: 기존 사이트 복호화 실패(비번 변경?) — 과거분 없이 새로 시작")
        return dict(empty)


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

  /* 핵심 3줄 / 오늘 꼭 볼 것 — 불릿을 강조 카드로(수치 배지+방향 컬러바) */
  .md ul.kul{padding-left:0;list-style:none;}
  .md ul.kul li{list-style:none;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);
    border-radius:0 10px 10px 0;padding:11px 14px;margin:8px 0;box-shadow:0 1px 2px rgba(16,24,40,.04);}
  .md ul.kul li.up{border-left-color:#e34948;}
  .md ul.kul li.down{border-left-color:#2563eb;}
  .kli-pct{display:inline-block;font-weight:800;font-size:12px;padding:2px 8px;border-radius:999px;
    margin:0 7px 2px 0;background:var(--chip);color:#374151;vertical-align:middle;white-space:nowrap;}
  .kli-pct.up{background:#fdeceb;color:#c0302f;}
  .kli-pct.down{background:#eaf1ff;color:var(--accent);}

  /* 공용 섹션 헤더(핵심 브리핑 하단 특수 키워드 등에서 재사용) */
  .core{margin:0 0 26px;}
  .core .lead{font-size:18px;font-weight:800;color:#111827;margin:0 0 3px;letter-spacing:-.01em;}
  .core .lead .q{font-weight:600;color:var(--muted);font-size:13px;}
  .core .sub{color:var(--muted);font-size:12.5px;line-height:1.55;margin:0 0 15px;}
  .kmore{color:var(--muted);font-size:12.5px;font-weight:700;margin:16px 0 9px;}
  .kchips{display:flex;flex-wrap:wrap;gap:7px;}
  .kchip{background:var(--chip);color:#374151;border:1px solid var(--line);border-radius:999px;
    padding:5px 11px;font-size:12.5px;cursor:pointer;white-space:nowrap;}
  .kchip:hover{background:#e2e7ef;} .kchip b{color:var(--accent);font-weight:800;}
  .core .empty{color:var(--muted);font-size:13.5px;background:var(--card);border:1px dashed var(--line);
    border-radius:12px;padding:16px;}
  .core .divider{border:0;border-top:1px solid var(--line);margin:26px 0 4px;}

  /* 키워드맵 — 게이트웨이 첫 화면. 원=키워드(크기 언급건수·진하기 채널수), 선=같은 기사 동시등장 */
  .nettoggle{color:var(--accent);cursor:pointer;font-weight:700;margin-left:6px;white-space:nowrap;}
  /* 모바일에서 줄여 맞추면 라벨이 안 읽혀 고정폭+가로스크롤(카드/표와 동일 패턴) */
  #netgraph{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px;overflow-x:auto;}
  .netsvg{width:800px;max-width:none;height:auto;display:block;}
  .netnode{cursor:pointer;}
  .netnode circle{transition:stroke-width .1s;}
  .netnode:hover circle,.netnode:focus circle{stroke:var(--accent);stroke-width:3;outline:none;}
  .netlabel{font-size:11px;font-weight:700;fill:#374151;pointer-events:none;}
  .nettable{width:100%;border-collapse:collapse;margin-top:4px;font-size:13px;background:var(--card);
    border:1px solid var(--line);border-radius:14px;overflow:hidden;}
  .nettable th,.nettable td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;}
  .nettable th.num,.nettable td.num{text-align:right;font-variant-numeric:tabular-nums;}
  .nettable tr:last-child td{border-bottom:0;}

  /* 특수 관심 키워드(배터리/리튬/EV 등 지정어) — 페이지 하단, 칩+건수만(.kchip 재사용) */
  .wmiss{color:var(--muted);font-size:12px;margin-top:14px;}

  /* 피드 */
  .feedbar{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;}
  .feedbar input[type=text],.feedbar input#q{flex:1;min-width:160px;}
  .sstoggle{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:13px;
    white-space:nowrap;user-select:none;cursor:pointer;}
  .ssbadge{font-size:11px;color:#b45309;background:#fef3c7;border-radius:6px;padding:2px 7px;margin-left:6px;}
  .meta{color:var(--muted);font-size:13px;margin:2px 0 14px;}
  .kfilter-chip{display:inline-block;background:var(--accent-soft);color:var(--accent);font-weight:700;
    border-radius:999px;padding:3px 10px;margin-right:8px;}
  .kfilter-chip b{cursor:pointer;font-weight:700;margin-left:2px;}
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
      <button class="tab active" data-view="net">키워드맵</button>
      <button class="tab" data-view="brief">핵심 브리핑</button>
      <button class="tab" data-view="feed">전체 피드</button>
    </div>
    <div class="spacer"></div>
    <select id="dateSel"></select>
    <button class="tab" id="logout" title="이 기기에서 비밀번호 기억 지우기">로그아웃</button>
  </header>
  <div class="wrap">
    <div id="netboard"></div>
    <div id="brief" class="md"></div>
    <div id="watchboard"></div>
    <div id="feed" class="hidden">
      <div class="feedbar">
        <select id="chSel"></select>
        <input id="q" placeholder="검색 (제목·본문)">
        <label class="sstoggle"><input type="checkbox" id="ssToggle"> 개별 소형주 포함</label>
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
let DATA=null, CUR=null, VIEW='net';

function dates(){ return Object.keys(DATA.briefings||{}).concat(Object.keys(DATA.feeds||{}))
  .filter((v,i,a)=>a.indexOf(v)===i).sort().reverse(); }
function label(k){ const m=(k||'').match(/^(\d{4}-\d{2}-\d{2})_(\d{2})$/); return m?`${m[1]} ${m[2]}시`:k; }

const SEQ_RAMP=['#9ec5f4','#6da7ec','#2a78d6','#1c5cab','#104281'];  // 100→700, 채널수 진하기

// 키워드맵 — 같은 기사에 함께 등장한 키워드끼리 선으로 연결(co-occurrence).
// shared/min(hits) 비가 낮은(우연히 한 번 겹친) 쌍은 걸러내 하이볼 잡음을 줄인다.
function cooccurEdges(kws, idx){
  const edges=[];
  for(let i=0;i<kws.length;i++){
    const A=idx[kws[i].kw]||[];
    if(!A.length) continue;
    const setA=new Set(A);
    for(let j=i+1;j<kws.length;j++){
      const B=idx[kws[j].kw]||[];
      if(!B.length) continue;
      let shared=0;
      B.forEach(x=>{ if(setA.has(x)) shared++; });
      if(!shared) continue;
      const minH=Math.min(kws[i].hits,kws[j].hits);
      if(shared>=Math.max(1,Math.ceil(minH*0.34))) edges.push({a:i,b:j,w:shared});
    }
  }
  return edges;
}

// 간단한 힘-기반(force-directed) 레이아웃 — 반발+스프링+중심인력, 고정 스텝수로 1회 수렴.
function layoutNetwork(nodes, edges, W, H){
  const n=nodes.length, cx=W/2, cy=H/2;
  nodes.forEach((nd,i)=>{
    const ang=n?i/n*Math.PI*2:0, rad=Math.min(W,H)*0.28;
    nd.x=cx+Math.cos(ang)*rad; nd.y=cy+Math.sin(ang)*rad; nd.vx=0; nd.vy=0;
  });
  for(let step=0;step<360;step++){
    nodes.forEach(nd=>{ nd.fx=(cx-nd.x)*0.006; nd.fy=(cy-nd.y)*0.006; });
    for(let i=0;i<n;i++){
      for(let j=i+1;j<n;j++){
        const dx=nodes[i].x-nodes[j].x, dy=nodes[i].y-nodes[j].y;
        const d2=Math.max(dx*dx+dy*dy,25), d=Math.sqrt(d2);
        const f=9000/d2, ux=dx/d, uy=dy/d;
        nodes[i].fx+=ux*f; nodes[i].fy+=uy*f;
        nodes[j].fx-=ux*f; nodes[j].fy-=uy*f;
      }
    }
    edges.forEach(e=>{
      const A=nodes[e.a], B=nodes[e.b];
      const dx=B.x-A.x, dy=B.y-A.y, d=Math.max(Math.sqrt(dx*dx+dy*dy),1);
      const rest=Math.max(64,190-e.w*22), f=(d-rest)*0.02, ux=dx/d, uy=dy/d;
      A.fx+=ux*f; A.fy+=uy*f; B.fx-=ux*f; B.fy-=uy*f;
    });
    nodes.forEach(nd=>{
      nd.vx=(nd.vx+nd.fx)*0.82; nd.vy=(nd.vy+nd.fy)*0.82;
      nd.x+=nd.vx; nd.y+=nd.vy;
    });
  }
  // 반경 인지 충돌 보정 — 원(+라벨 여유공간)이 겹치지 않도록 직접 밀어냄.
  // 힘 시뮬레이션은 점 질량 기준이라 큰 원끼리는 겹칠 수 있어 마무리 패스로 보정.
  for(let pass=0;pass<120;pass++){
    let moved=false;
    for(let i=0;i<n;i++){
      for(let j=i+1;j<n;j++){
        const A=nodes[i], B=nodes[j];
        const dx=B.x-A.x, dy=B.y-A.y;
        const d=Math.sqrt(dx*dx+dy*dy)||0.01;
        const minD=(A.r||14)+(B.r||14)+24;
        if(d<minD){
          const push=(minD-d)/2, ux=dx/d, uy=dy/d;
          A.x-=ux*push; A.y-=uy*push;
          B.x+=ux*push; B.y+=uy*push;
          moved=true;
        }
      }
    }
    if(!moved) break;
  }
  const pad=52;
  nodes.forEach(nd=>{
    const m=pad+(nd.r||14);
    nd.x=Math.min(W-m,Math.max(m,nd.x)); nd.y=Math.min(H-m,Math.max(m,nd.y));
  });
}

let NET_TABLE=false;
function renderNet(){
  const el=document.getElementById('netboard');
  const kd=(DATA.keywords||{})[CUR];
  const kws=(kd&&kd.kws)||[];
  if(!kws.length){
    el.innerHTML=`<div class="core"><div class="lead">🕸️ 키워드맵</div>
      <div class="empty">이 날짜엔 반복 키워드 데이터가 없습니다 — 핵심 브리핑 탭을 확인하세요.</div><hr class="divider"></div>`;
    return;
  }
  const idx=kd.idx||{};
  const W=800,H=520;
  const maxHits=Math.max(1,...kws.map(k=>k.hits));
  const rNode=k=>Math.round(14+Math.sqrt(k.hits/maxHits)*22);
  const nodes=kws.map(k=>({kw:k.kw,hits:k.hits,channels:k.channels,macro:k.macro,head:k.head,r:rNode(k)}));
  const edges=cooccurEdges(kws, idx);
  layoutNetwork(nodes, edges, W, H);
  const maxW=Math.max(1,...edges.map(e=>e.w));
  // 채널수는 날짜마다 범위가 크게 달라(2~14) 고정 임계값이면 진한 쪽에 다 몰림 —
  // 그날의 최소~최대 범위로 상대 스케일링해 진하기 차이가 실제로 보이게 한다.
  const chVals=kws.map(k=>k.channels), minCh=Math.min(...chVals), maxCh=Math.max(...chVals);
  const fillNode=k=>{
    const t=maxCh>minCh?(k.channels-minCh)/(maxCh-minCh):1;
    return SEQ_RAMP[Math.min(SEQ_RAMP.length-1,Math.round(t*(SEQ_RAMP.length-1)))];
  };
  const edgeSvg=edges.map(e=>{
    const A=nodes[e.a], B=nodes[e.b];
    const sw=(0.6+e.w/maxW*2.2).toFixed(2), op=(0.18+e.w/maxW*0.42).toFixed(2);
    return `<line x1="${A.x.toFixed(1)}" y1="${A.y.toFixed(1)}" x2="${B.x.toFixed(1)}" y2="${B.y.toFixed(1)}" stroke="#9aa7bb" stroke-width="${sw}" opacity="${op}"/>`;
  }).join('');
  const nodeSvg=nodes.map(nd=>{
    const r=nd.r, fill=fillNode(nd);
    return `<g class="netnode" data-kw="${esc(nd.kw)}" tabindex="0">
      <title>${esc(nd.kw)} · ${nd.hits}건 · ${nd.channels}개 채널${nd.head?(' · '+esc(nd.head)):''}</title>
      <circle cx="${nd.x.toFixed(1)}" cy="${nd.y.toFixed(1)}" r="${r}" fill="${fill}" stroke="#fff" stroke-width="2"></circle>
      <text x="${nd.x.toFixed(1)}" y="${(nd.y+r+13).toFixed(1)}" text-anchor="middle" class="netlabel">${nd.macro?'🌐 ':''}${esc(nd.kw)}</text>
    </g>`;
  }).join('');
  const tableRows=kws.map(k=>`<tr><td>${k.macro?'🌐 ':''}${esc(k.kw)}</td><td class="num">${k.hits}</td><td class="num">${k.channels}</td></tr>`).join('');
  el.innerHTML=`<div class="core">
    <div class="lead">🕸️ 키워드맵 <span class="q">— 오늘 반복된 이슈들의 연결</span></div>
    <div class="sub">원 크기=언급 건수, 진할수록 더 많은 채널이 함께 다뤘습니다. 선은 같은 기사에 함께 등장한 키워드끼리 이어집니다.
      개별 소형주 ${(kd.n_noise||0)}건 집계 제외 · 수집 ${(kd.n_items||0)}건. 원을 누르면 관련 뉴스만 볼 수 있어요.
      <span class="nettoggle" id="netToggle">표로 보기</span></div>
    <div id="netgraph"><svg viewBox="0 0 ${W} ${H}" class="netsvg" role="img" aria-label="키워드 연결망">${edgeSvg}${nodeSvg}</svg></div>
    <table class="nettable hidden" id="netTable"><thead><tr><th>키워드</th><th class="num">건수</th><th class="num">채널</th></tr></thead><tbody>${tableRows}</tbody></table>
    <hr class="divider"></div>`;
  el.querySelectorAll('.netnode').forEach(n=>{
    n.onclick=()=>kfilter(n.dataset.kw);
    n.onkeydown=e=>{ if(e.key==='Enter') kfilter(n.dataset.kw); };
  });
  const tg=document.getElementById('netToggle');
  tg.onclick=()=>{
    NET_TABLE=!NET_TABLE;
    document.getElementById('netgraph').classList.toggle('hidden',NET_TABLE);
    document.getElementById('netTable').classList.toggle('hidden',!NET_TABLE);
    tg.textContent=NET_TABLE?'그래프로 보기':'표로 보기';
  };
}
let KFILTER_IDX=null, KFILTER_LABEL=null;   // 키워드/관심어 클릭 드릴다운 — 정확한 인덱스로만 필터
function applyFilter(idxArr, label){
  KFILTER_IDX=idxArr||[];
  KFILTER_LABEL=label;
  document.getElementById('chSel').value='';
  document.getElementById('ssToggle').checked=true;   // 정확 매칭이니 소형주 숨김으로 결과가 사라지지 않게
  document.getElementById('q').value='';
  setView('feed');
}
function kfilter(kw){   // '오늘의 핵심' 막대 — 랭킹을 만든 근거(헤드라인)로 정확히 필터
  const kd=(DATA.keywords||{})[CUR]||{};
  applyFilter((kd.idx&&kd.idx[kw])||[], kw);
}
function wfilter(term){   // '특수 관심 키워드' 칩 — 지정어 매칭 인덱스로 필터
  const wd=(DATA.watchlist||{})[CUR]||{};
  applyFilter(wd[term]||[], term);
}
function clearKfilter(){ KFILTER_IDX=null; KFILTER_LABEL=null; render(); }
function enhanceBrief(){   // 핵심 3줄/오늘 꼭 볼 것 불릿 → 수치 배지+방향 컬러 카드로 강조
  const brief=document.getElementById('brief');
  brief.querySelectorAll('h2, h3').forEach(h=>{
    if(!/핵심\s*3줄|오늘\s*꼭\s*볼\s*것/.test(h.textContent)) return;
    const ul=h.nextElementSibling;
    if(!ul||ul.tagName!=='UL') return;
    ul.classList.add('kul');
    ul.querySelectorAll(':scope > li').forEach(li=>{
      const t=li.textContent;
      const m=t.match(/[+-]\d+(\.\d+)?\s?%/)||t.match(/\d+(\.\d+)?\s?%/);
      if(!m) return;
      let dir=null;
      if(/^\+/.test(m[0])||/상승|급등|돌파|확대|증가/.test(t)) dir='up';
      if(/^-/.test(m[0])||/하락|급락|붕괴|축소|감소/.test(t)) dir='down';
      if(dir) li.classList.add(dir);
      const b=document.createElement('span');
      b.className='kli-pct '+(dir||'');
      b.textContent=m[0].replace(/\s/g,'');
      li.prepend(b);
    });
  });
}
function renderBrief(){
  const md=(DATA.briefings||{})[CUR], brief=document.getElementById('brief');
  if(md && md.indexOf('자동 추출 요약')<0){ brief.innerHTML=marked.parse(md); enhanceBrief(); }  // AI 종합 브리핑
  else if(!md) brief.innerHTML='<p class="meta" style="margin-top:8px">이 날짜의 AI 종합 브리핑은 없습니다. 위 핵심 키워드를 참고하세요.</p>';
  else brief.innerHTML='';   // 자동추출 키워드 마크다운은 위 보드로 대체(중복 제거)
  renderWatch();
}
function renderWatch(){   // 배터리/리튬/EV 등 지정 관심 키워드 — 칩만 표시, 누르면 전체피드로 드릴다운
  const el=document.getElementById('watchboard');
  const terms=(DATA.meta&&DATA.meta.watch_terms)||[];
  if(!terms.length){ el.innerHTML=''; return; }
  const wd=(DATA.watchlist||{})[CUR]||{};
  const hit=terms.filter(t=>wd[t]&&wd[t].length);
  const miss=terms.filter(t=>!hit.includes(t));
  let h=`<div class="lead">🔎 특수 관심 키워드</div>
    <div class="sub">배터리·소재·전기차 등 지정 키워드 — 누르면 전체 피드에서 해당 뉴스만 볼 수 있어요.</div>`;
  if(!hit.length){
    h+=`<div class="empty">오늘은 지정 키워드 언급이 없습니다.</div>`;
  } else {
    h+=`<div class="kchips">${hit.map(t=>
      `<span class="kchip" data-term="${esc(t)}">${esc(t)} <b>${wd[t].length}</b></span>`).join('')}</div>`;
    if(miss.length) h+=`<div class="wmiss">오늘 언급 없음: ${esc(miss.join(', '))}</div>`;
  }
  el.innerHTML=`<div class="core">${h}</div>`;
  el.querySelectorAll('[data-term]').forEach(n=>n.onclick=()=>wfilter(n.dataset.term));
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
  const showSS=document.getElementById('ssToggle').checked;
  let rows=feed;
  if(KFILTER_IDX) rows=rows.filter((_,i)=>KFILTER_IDX.includes(i));   // 인덱스 순서 유지한 채로 먼저 적용
  rows=rows.slice().reverse();
  if(ch) rows=rows.filter(r=>r.ch===ch);
  if(q) rows=rows.filter(r=>JSON.stringify(r).toLowerCase().includes(q));
  const nSS=rows.filter(r=>r.ss).length;
  if(!showSS) rows=rows.filter(r=>!r.ss);
  const kchip=KFILTER_IDX?`<span class="kfilter-chip">🔑 ${esc(KFILTER_LABEL)} 매칭 <b onclick="clearKfilter()">해제 ✕</b></span>`:'';
  document.getElementById('feedMeta').innerHTML = kchip +
    `${rows.length}건` + (!showSS && nSS ? ` · 개별 소형주 ${nSS}건 숨김` : '');
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
  const ssb=r.ss?'<span class="ssbadge">개별종목</span>':'';
  return `<div class="card"><div class="top"><span class="chip">${esc(r.ch)}</span><span class="time">${t}${ssb}</span></div>
    <div class="head">${esc(r.head)}</div>${sum}${arts}<div class="links">${links.join('')}</div></div>`;
}
function render(){ if(VIEW==='net') renderNet(); else if(VIEW==='brief') renderBrief(); else renderFeed(); }

function setView(v){ VIEW=v;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.view===v));
  document.getElementById('netboard').classList.toggle('hidden',v!=='net');
  document.getElementById('brief').classList.toggle('hidden',v!=='brief');
  document.getElementById('watchboard').classList.toggle('hidden',v!=='brief');
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
  const ds=dates(); sel.innerHTML=ds.map(d=>`<option value="${d}">${label(d)}</option>`).join('');
  CUR=ds[0]; sel.onchange=()=>{CUR=sel.value;KFILTER_IDX=null;KFILTER_LABEL=null;render();};
  document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{KFILTER_IDX=null;KFILTER_LABEL=null;setView(t.dataset.view);});
  document.getElementById('chSel').onchange=renderFeed;
  document.getElementById('q').oninput=renderFeed;
  document.getElementById('ssToggle').onchange=renderFeed;
  document.getElementById('logout').onclick=()=>{localStorage.removeItem('mb_pw');location.reload();};
  setView('net');
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
    keywords = dict(prior["keywords"]); keywords.update(local_keywords())
    watchlist = dict(prior["watchlist"]); watchlist.update(local_watchlist())

    plain = json.dumps(
        {"meta": {"built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                  "watch_terms": config.watch_terms()},
         "briefings": briefings, "feeds": feeds, "keywords": keywords, "watchlist": watchlist},
        ensure_ascii=False,
    )
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(HTML.replace("__PAYLOAD__", json.dumps(encrypt(plain, password))), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"docs/index.html 생성 (브리핑 {len(briefings)}일 · 피드 {sum(len(v) for v in feeds.values())}건, 암호화됨)")


if __name__ == "__main__":
    main()
