"""마켓 브리핑 검증용 로컬 뷰어.

왼쪽: 수집된 텔레그램 원본 메시지 / 오른쪽: 생성된 브리핑(렌더링).
실행:  python viewer.py   →  http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from flask import Flask, abort, jsonify

ROOT = Path(__file__).resolve().parent
BRIEFINGS = ROOT / "briefings"

app = Flask(__name__)

INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>데일리 마켓 브리핑 · 뷰어</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --fg:#e6e9ef; --muted:#9aa4b2; --accent:#5b9dff; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Segoe UI",sans-serif;
         background:var(--bg); color:var(--fg); }
  header { padding:14px 20px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:16px;
           position:sticky; top:0; background:var(--bg); z-index:5; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  header .sub { color:var(--muted); font-size:13px; }
  select { background:var(--panel); color:var(--fg); border:1px solid var(--line); border-radius:8px;
           padding:6px 10px; font-size:14px; }
  .wrap { display:grid; grid-template-columns:minmax(320px, 1fr) minmax(420px, 1.4fr); gap:0; height:calc(100vh - 53px); }
  .col { overflow-y:auto; padding:18px 22px; }
  .col.left { border-right:1px solid var(--line); }
  .col h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
            margin:0 0 14px; font-weight:600; }
  .msg { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:10px; }
  .msg .meta { display:flex; justify-content:space-between; gap:10px; font-size:12px; color:var(--muted); margin-bottom:6px; }
  .msg .ch { color:var(--accent); font-weight:600; }
  .msg .body { font-size:14px; line-height:1.55; white-space:pre-wrap; }
  .msg a { color:var(--muted); font-size:12px; text-decoration:none; }
  .msg a:hover { color:var(--accent); text-decoration:underline; }
  .md { font-size:15px; line-height:1.7; max-width:820px; }
  .md h3 { margin-top:26px; padding-bottom:6px; border-bottom:1px solid var(--line); font-size:18px; }
  .md h1,.md h2 { font-size:20px; }
  .md blockquote { border-left:3px solid var(--accent); margin:0 0 18px; padding:8px 14px; background:var(--panel);
                   border-radius:0 8px 8px 0; color:var(--muted); font-size:13.5px; }
  .md code { background:var(--panel); padding:1px 5px; border-radius:4px; font-size:13px; }
  .md pre { background:var(--panel); padding:12px; border-radius:8px; overflow-x:auto; }
  .md a { color:var(--accent); }
  .md ul { padding-left:20px; }
  .md li { margin:4px 0; }
  .md hr { border:0; border-top:1px solid var(--line); margin:22px 0; }
  .empty { color:var(--muted); padding:40px; text-align:center; }
  .count { color:var(--muted); font-weight:400; font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>📰 데일리 마켓 브리핑 <span class="count">· 검증 뷰어</span></h1>
  <span class="sub">날짜</span>
  <select id="dateSel"></select>
  <span class="sub" id="status"></span>
</header>
<div class="wrap">
  <div class="col left">
    <h2>수집 원본 메시지 <span class="count" id="msgCount"></span></h2>
    <div id="messages"></div>
  </div>
  <div class="col right">
    <h2>생성된 브리핑</h2>
    <div class="md" id="briefing"></div>
  </div>
</div>
<script>
async function loadDates() {
  const res = await fetch('/api/dates');
  const dates = await res.json();
  const sel = document.getElementById('dateSel');
  sel.innerHTML = '';
  if (!dates.length) {
    document.getElementById('status').textContent = '브리핑 파일이 없습니다.';
    return;
  }
  dates.forEach(d => { const o=document.createElement('option'); o.value=d; o.textContent=d; sel.appendChild(o); });
  sel.onchange = () => loadData(sel.value);
  loadData(dates[0]);
}
async function loadData(date) {
  const res = await fetch('/api/data/' + date);
  if (!res.ok) { document.getElementById('status').textContent='로드 실패'; return; }
  const data = await res.json();
  document.getElementById('status').textContent = '';
  // messages
  const box = document.getElementById('messages');
  box.innerHTML = '';
  document.getElementById('msgCount').textContent = '(' + data.messages.length + '건)';
  data.messages.forEach(m => {
    const div = document.createElement('div'); div.className='msg';
    const t = (m.timestamp||'').replace('T',' ').slice(0,16);
    const link = m.link ? `<a href="${m.link}" target="_blank">원문 링크 ↗</a>` : `<span></span>`;
    div.innerHTML = `<div class="meta"><span class="ch">${escapeHtml(m.channel||'')}</span><span>${t}</span></div>`
      + `<div class="body">${escapeHtml(m.text||'')}</div>`
      + `<div style="margin-top:6px">${link}</div>`;
    box.appendChild(div);
  });
  // briefing
  document.getElementById('briefing').innerHTML = marked.parse(data.markdown || '');
}
function escapeHtml(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
loadDates();
</script>
</body>
</html>"""


def _dates() -> list[str]:
    out = []
    for p in sorted(BRIEFINGS.glob("briefing_*.md"), reverse=True):
        m = re.match(r"briefing_(\d{4}-\d{2}-\d{2})\.md", p.name)
        if m:
            out.append(m.group(1))
    return out


@app.get("/")
def index():
    return INDEX_HTML


@app.get("/api/dates")
def api_dates():
    return jsonify(_dates())


@app.get("/api/data/<date>")
def api_data(date: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        abort(400)
    md_path = BRIEFINGS / f"briefing_{date}.md"
    raw_path = BRIEFINGS / f"raw_{date}.json"
    if not md_path.exists():
        abort(404)
    messages = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else []
    return jsonify({"markdown": md_path.read_text(encoding="utf-8"), "messages": messages})


if __name__ == "__main__":
    print("뷰어 실행: http://127.0.0.1:8765")
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)
