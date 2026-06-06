"""Mode C (dashboard) 단위 위젯 JS 렌더러 — SESSION_SHELL_HTML 조립용 string export.

Issue30: server.py 에서 추출. renderWidget 9종(progress/table/checklist/text
/chart/log/diff/timer/badge) 단일 함수 포함.
"""

WIDGET_JS = r"""
// Issue19 Phase 3: Mode C dashboard renderer (widget 단위)
function renderWidget(w) {
  if (!w || typeof w !== 'object') return `<div class="widget unknown">invalid widget</div>`;
  const title = w.title ? `<div class="w-title">${esc(w.title)}</div>` : '';
  switch (w.type) {
    case 'progress': {
      const pct = typeof w.value === 'number' ? Math.max(0, Math.min(100, w.value)) : 0;
      return `<div class="widget progress">${title}<div class="bar"><div class="bar-fill" style="width:${pct}%"></div></div><div class="pct">${pct}%${w.label ? ' — ' + esc(w.label) : ''}</div></div>`;
    }
    case 'table': {
      const rows = Array.isArray(w.rows) ? w.rows : [];
      const headers = Array.isArray(w.headers) ? w.headers : (rows[0] ? Object.keys(rows[0]) : []);
      const thead = headers.length ? `<thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>` : '';
      const tbody = rows.map(r => {
        const cells = Array.isArray(r) ? r : headers.map(h => r[h]);
        return `<tr>${cells.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`;
      }).join('');
      return `<div class="widget table">${title}<table>${thead}<tbody>${tbody}</tbody></table></div>`;
    }
    case 'checklist': {
      const items = Array.isArray(w.items) ? w.items : [];
      const lis = items.map(it => {
        const done = (typeof it === 'object' && it.done) ? 'done' : '';
        const text = typeof it === 'object' ? (it.text || it.label || '') : String(it);
        const mark = done ? '☑' : '☐';
        return `<li class="${done}">${mark} ${esc(text)}</li>`;
      }).join('');
      return `<div class="widget checklist">${title}<ul>${lis}</ul></div>`;
    }
    case 'text': {
      return `<div class="widget text">${title}<pre>${esc(w.content || w.text || '')}</pre></div>`;
    }
    case 'chart': {
      const series = Array.isArray(w.series) ? w.series.filter(n => typeof n === 'number') : [];
      if (!series.length) return `<div class="widget chart">${title}<em>(no data)</em></div>`;
      const kind = w.kind === 'line' ? 'line' : 'bar';
      const W = 280, H = 60, pad = 2;
      const min = Math.min(...series, 0), max = Math.max(...series, 1);
      const range = max - min || 1;
      const stepX = series.length > 1 ? (W - pad * 2) / (series.length - 1) : 0;
      const barW = series.length ? (W - pad * 2) / series.length : 0;
      const y = v => H - pad - ((v - min) / range) * (H - pad * 2);
      let svg = '';
      if (kind === 'bar') {
        svg = series.map((v, i) => {
          const h = ((v - min) / range) * (H - pad * 2);
          return `<rect class="chart-bar" x="${pad + i * barW + 1}" y="${H - pad - h}" width="${Math.max(1, barW - 2)}" height="${h}"/>`;
        }).join('');
      } else {
        const pts = series.map((v, i) => `${pad + i * stepX},${y(v)}`).join(' ');
        const dots = series.map((v, i) => `<circle class="chart-dot" cx="${pad + i * stepX}" cy="${y(v)}" r="2"/>`).join('');
        svg = `<polyline class="chart-line" points="${pts}"/>${dots}`;
      }
      const lastLabel = w.label ? esc(w.label) : `${series[series.length - 1]} (n=${series.length})`;
      return `<div class="widget chart">${title}<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${svg}</svg><div class="chart-label">${lastLabel}</div></div>`;
    }
    case 'log': {
      // Issue77 (글로벌 .claude#Issue91 짝): log 위젯은 monospace + 세로 스크롤 영역.
      //   .log-box CSS = font-family monospace + max-height + overflow-y:auto + white-space:pre-wrap
      //   → 긴 줄은 wrap 되어 클리핑(보이지 않음) 없음. width:'full' 위젯과 함께 쓰면 전폭 가독.
      const lines = Array.isArray(w.lines) ? w.lines : [];
      const max = (typeof w.max === 'number' && w.max > 0) ? w.max : 20;
      const tail = lines.slice(-max);
      const html = tail.map(l => `<div class="log-line">${esc(String(l))}</div>`).join('');
      return `<div class="widget log">${title}<div class="log-box">${html || '<em>(empty)</em>'}</div></div>`;
    }
    case 'diff': {
      const before = w.before != null ? String(w.before) : '';
      const after = w.after != null ? String(w.after) : '';
      return `<div class="widget diff">${title}<div class="diff-grid"><div class="diff-col before"><div class="diff-label">before</div>${esc(before)}</div><div class="diff-col after"><div class="diff-label">after</div>${esc(after)}</div></div></div>`;
    }
    case 'timer': {
      const startTs = typeof w.start_ts === 'number' ? w.start_ts : 0;
      const mode = w.mode === 'down' ? 'down' : 'up';
      const target = typeof w.target === 'number' ? w.target : 0;
      return `<div class="widget timer" data-start-ts="${startTs}" data-mode="${mode}" data-target="${target}">${title}<div class="timer-value">…</div><div class="timer-mode">${mode}</div></div>`;
    }
    case 'badge': {
      const label = w.label != null ? String(w.label) : '';
      const color = String(w.color || 'info');
      const presets = ['ok', 'warn', 'err', 'info'];
      let cls = '', dotStyle = '';
      if (presets.includes(color)) {
        cls = ' ' + color;
      } else {
        dotStyle = ` style="background: ${esc(color)}"`;
      }
      return `<div class="widget badge${cls}">${title}<span class="badge-dot"${dotStyle}></span><span class="badge-label">${esc(label)}</span></div>`;
    }
    case 'graph': {
      // Issue66: DAG 큐 시각화 — 위상 레벨별 열 배치, 외부 라이브러리 없이 SVG 직접 생성
      const nodes = Array.isArray(w.nodes) ? w.nodes : [];
      const edges = Array.isArray(w.edges) ? w.edges : [];
      if (!nodes.length) return `<div class="widget graph">${title}<em>(no nodes)</em></div>`;
      // 각 노드 id -> index 매핑
      const idMap = {};
      nodes.forEach((n, i) => { idMap[n.id] = i; });
      // 위상 정렬 — depends 깊이(최장 경로)로 column index 결정
      const depth = new Array(nodes.length).fill(0);
      const inEdges = nodes.map(() => []);
      edges.forEach(e => {
        const fi = idMap[e.from], ti = idMap[e.to];
        if (fi != null && ti != null) inEdges[ti].push(fi);
      });
      // BFS/반복으로 최장 경로 깊이 계산.
      // cycle edges(a→b→c→a) 입력 시 무한루프 방지 — iteration 상한 nodes.length+1.
      // 정상 DAG 는 최장 경로 길이 ≤ nodes.length 안에 수렴한다.
      let changed = true, iter = 0;
      while (changed && iter++ < nodes.length + 1) {
        changed = false;
        nodes.forEach((_, i) => {
          inEdges[i].forEach(pi => {
            if (depth[pi] + 1 > depth[i]) { depth[i] = depth[pi] + 1; changed = true; }
          });
        });
      }
      // 열별 노드 배치
      const cols = {};
      nodes.forEach((_, i) => {
        const c = depth[i];
        if (!cols[c]) cols[c] = [];
        cols[c].push(i);
      });
      const colKeys = Object.keys(cols).map(Number).sort((a,b)=>a-b);
      // 레이아웃 상수
      const NW = 110, NH = 36, HGAP = 60, VGAP = 54, PADX = 16, PADY = 16;
      const maxRows = Math.max(...colKeys.map(c => cols[c].length));
      const svgW = colKeys.length * (NW + HGAP) + PADX * 2;
      const svgH = maxRows * (NH + VGAP) + PADY * 2;
      // 노드 위치 계산
      const pos = new Array(nodes.length);
      colKeys.forEach((c, ci) => {
        const col = cols[c];
        col.forEach((ni, ri) => {
          const totalH = col.length * (NH + VGAP) - VGAP;
          const startY = (svgH - totalH) / 2;
          pos[ni] = {
            x: PADX + ci * (NW + HGAP),
            y: startY + ri * (NH + VGAP)
          };
        });
      });
      // 상태별 색 (Issue66 P7: waiting_approval 추가 — 승인 게이트)
      const STATUS_COLORS = {
        done: '#4caf50', running: '#2196f3', blocked: '#9e9e9e',
        waiting_input: '#ff9800', waiting_approval: '#e8a020',
        failed: '#f44336', withdrawn: '#bdbdbd'
      };
      // 노드 SVG 생성
      const nodesSvg = nodes.map((n, i) => {
        const p = pos[i];
        const color = STATUS_COLORS[n.status] || '#9e9e9e';
        const label = String(n.label || n.id);
        const shortLabel = label.length > 14 ? label.slice(0, 13) + '…' : label;
        const hasAction = n.action && n.action.type === 'link' && n.action.url;
        const cursor = hasAction ? 'pointer' : 'default';
        const dataUrl = hasAction ? ` data-url="${esc(n.action.url)}"` : '';
        return `<g class="graph-node" style="cursor:${cursor}"${dataUrl} onclick="(function(el){const u=el.getAttribute('data-url');if(u){const w=window.open(u,'_blank','noopener');if(!w){window.open(u,'_blank');}};})(this)">
          <rect x="${p.x}" y="${p.y}" width="${NW}" height="${NH}" rx="6" fill="${color}" stroke="#fff" stroke-width="1.5"/>
          <text x="${p.x + NW/2}" y="${p.y + NH/2 + 5}" text-anchor="middle" font-size="12" fill="#fff" font-family="sans-serif">${esc(shortLabel)}</text>
        </g>`;
      }).join('');
      // 엣지 SVG 생성
      const edgesSvg = edges.map(e => {
        const fi = idMap[e.from], ti = idMap[e.to];
        if (fi == null || ti == null) return '';
        const fp = pos[fi], tp = pos[ti];
        const x1 = fp.x + NW, y1 = fp.y + NH / 2;
        const x2 = tp.x, y2 = tp.y + NH / 2;
        const cx = (x1 + x2) / 2;
        return `<path d="M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}" fill="none" stroke="#aaa" stroke-width="1.5" marker-end="url(#arrowhead)"/>`;
      }).join('');
      const defs = `<defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#aaa"/></marker></defs>`;
      return `<div class="widget graph">${title}<div style="overflow:auto"><svg viewBox="0 0 ${svgW} ${svgH}" width="${svgW}" height="${svgH}" style="max-width:100%;display:block">${defs}${edgesSvg}${nodesSvg}</svg></div></div>`;
    }
    default:
      return `<div class="widget unknown">${title}unknown widget: ${esc(w.type || '(none)')}</div>`;
  }
}
"""
