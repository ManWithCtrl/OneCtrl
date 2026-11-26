/* 根轨迹工作台：den + K*num 的闭环极点随 K 变化。
 * 纯前端 SVG；与 M1 的模型系数共用，独立 K 滑块。
 */
(function () {
  'use strict';
  const LC = window.LiveCore;
  if (!LC) return;
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const VB = 360, CX = 180, CY = 166, HALF = 132;
  const KMIN = 1e-2, KMAX = 1000;

  const S = {
    model: null, num: [], den: [], K: 1, panX: 0, panY: 0,
    poles: [], zeros: [], branches: [], breakaways: [], asymptotes: [],
    R: 1, Rbase: 1, fitR: 1, fitPending: true, zoom: 1, layout: null,
  };

  function add(parent, tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    parent.appendChild(e);
    return e;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  /* 数值噪声吸附：几何量落在 1e-6 以内就当 0，避免显示 8.66e-13 这类假精度 */
  const snapv = (v) => (Math.abs(v) < 1e-6 ? 0 : v);
  function fmt(v, n) {
    if (!isFinite(v)) return '—';
    const a = Math.abs(v);
    if (a !== 0 && (a >= 1e4 || a < 1e-3)) return v.toExponential(1);
    return (+v).toFixed(n == null ? 2 : n).replace(/\.?0+$/, '');
  }
  function text(parent, x, y, s, cls, anchor) {
    const t = add(parent, 'text', { x: x, y: y, class: cls || 'rl-ax', 'text-anchor': anchor || 'middle' });
    t.textContent = s;
    return t;
  }
  function sortRoots(rs) {
    return rs.slice().sort((a, b) => (a.re - b.re) || (a.im - b.im));
  }
  function clRoots(k) {
    return LC.roots(LC.polyadd(S.den, LC.polyscale(S.num, k)));
  }
  function deriv(c) {
    const n = c.length - 1;
    return c.slice(0, n).map((v, i) => v * (n - i));
  }
  /* ---------- 分支追踪 ----------
     每个分支各自「从上一刻的根线性外推 + 牛顿修正」求根本身，再对齐到真实根集合。
     比逐点最近邻/整体最优匹配稳：分离点、会合点处两条分支贴得极近，匹配一旦互换，
     折线就会画出一条突然折返的长直线（看上去就是「断了一截」）。 */
  const cadd = (a, b) => ({ re: a.re + b.re, im: a.im + b.im });
  const csub = (a, b) => ({ re: a.re - b.re, im: a.im - b.im });
  const cscale = (a, k) => ({ re: a.re * k, im: a.im * k });
  const cdiv = (a, b) => {
    const d = b.re * b.re + b.im * b.im;
    return { re: (a.re * b.re + a.im * b.im) / d, im: (a.im * b.re - a.re * b.im) / d };
  };
  const cabs2 = (a) => a.re * a.re + a.im * a.im;
  const cdist = (a, b) => Math.hypot(a.re - b.re, a.im - b.im);

  function newtonRoot(k, s0) {
    let s = { re: s0.re, im: s0.im };
    for (let it = 0; it < 40; it++) {
      const d = cadd(LC.polyval(S.dder, s), cscale(LC.polyval(S.nder, s), k));
      if (cabs2(d) < 1e-30) break;
      const step = cdiv(cadd(LC.polyval(S.den, s), cscale(LC.polyval(S.num, s), k)), d);
      s = csub(s, step);
      if (cabs2(step) < 1e-18) break;
    }
    const res = Math.sqrt(cabs2(cadd(LC.polyval(S.den, s), cscale(LC.polyval(S.num, s), k))));
    return { s, res };
  }

  /* 分支生成：N0 个对数 K 网格点连续追踪，再按弦高/段长自适应加密 */
  function buildBranches() {
    S.branches = [];
    if (!S.den.length || S.den.length < 2) return;
    S.dder = deriv(S.den);
    S.nder = deriv(S.num);
    let ext = 1;
    for (const z of S.poles.concat(S.zeros)) ext = Math.max(ext, Math.hypot(z.re, z.im));

    const pts = sortRoots(clRoots(KMIN)).map((p) => [{ k: KMIN, re: p.re, im: p.im }]);
    let prev = pts.map((p) => ({ re: p[0].re, im: p[0].im }));
    let prev2 = null;
    const N0 = 120;
    for (let i = 1; i <= N0; i++) {
      const k = KMIN * Math.pow(KMAX / KMIN, i / N0);
      const all = clRoots(k);
      const used = new Array(all.length).fill(false);
      const next = new Array(prev.length);
      for (let b = 0; b < prev.length; b++) {
        const pred = prev2
          ? { re: 2 * prev[b].re - prev2[b].re, im: 2 * prev[b].im - prev2[b].im }
          : { re: prev[b].re, im: prev[b].im };
        const cand = newtonRoot(k, pred);
        let best = -1, bd = Infinity;
        if (cand.res < 1e-9) {
          for (let j = 0; j < all.length; j++) {
            if (used[j]) continue;
            const d = cdist(all[j], cand.s);
            if (d < bd) { bd = d; best = j; }
          }
        }
        if (best < 0 || bd > 1e-3) {                 // 牛顿没咬住：退回最近的未占用根
          best = -1;
          bd = Infinity;
          for (let j = 0; j < all.length; j++) {
            if (used[j]) continue;
            const d = cdist(all[j], pred);
            if (d < bd) { bd = d; best = j; }
          }
        }
        if (best < 0) { next[b] = prev[b]; continue; }
        used[best] = true;
        next[b] = all[best];
      }
      for (let b = 0; b < next.length; b++) pts[b].push({ k, re: next[b].re, im: next[b].im });
      prev2 = prev;
      prev = next;
    }

    const tol = Math.max(5e-5, Math.max(ext * 1.8, 8) * 0.0025);   // 弦高 ≈0.3px
    const maxSeg = Math.max(ext * 0.018, 0.1);                     // 相邻点间距 ≈1.5px
    let budget = 16000;
    const sub = (arr, kL, pL, kR, pR, depth) => {
      if (budget <= 0 || depth <= 0) return;
      const km = Math.sqrt(kL * kR);
      if (!(km > kL && km < kR)) return;
      const chord = cdist(pL, pR);
      const g = newtonRoot(km, { re: (pL.re + pR.re) / 2, im: (pL.im + pR.im) / 2 });
      if (g.res > 1e-9) return;
      const dev = chord < 1e-12
        ? cdist(pL, g.s)
        : Math.abs((g.s.re - pL.re) * (pR.im - pL.im) - (g.s.im - pL.im) * (pR.re - pL.re)) / chord;
      if (dev <= tol && chord <= maxSeg) return;
      budget--;
      arr.push({ k: km, re: g.s.re, im: g.s.im });
      sub(arr, kL, pL, km, g.s, depth - 1);
      sub(arr, km, g.s, kR, pR, depth - 1);
    };
    for (const arr of pts) {
      const base = arr.slice();
      for (let i = 1; i < base.length; i++) sub(arr, base[i - 1].k, base[i - 1], base[i].k, base[i], 10);
      arr.sort((x, y) => x.k - y.k);
      S.branches.push(arr.map((p) => [p.re, p.im]));
    }
  }

  function build(model) {
    S.num = (model.ol_num || []).slice();
    S.den = (model.ol_den || []).slice();
    S.poles = LC.roots(S.den);
    S.zeros = LC.roots(S.num);
    buildBranches();

    const numd = deriv(S.num), dend = deriv(S.den);
    const eq = LC.polyadd(LC.polymul(numd, S.den), LC.polyscale(LC.polymul(S.num, dend), -1));
    S.breakaways = [];
    for (const r of LC.roots(eq)) {
      if (Math.abs(r.im) > 1e-6) continue;
      const s = r.re;
      const sv = { re: s, im: 0 };
      const nv = LC.polyval(S.num, sv), dv = LC.polyval(S.den, sv);
      if (Math.abs(nv.re) < 1e-12) continue;
      const k = -dv.re / nv.re;
      if (isFinite(k) && k > 0 && S.breakaways.every((b) => Math.abs(b.s - s) > 1e-6)) {
        S.breakaways.push({ s, k });
      }
    }

    S.asymptotes = [];
    const n = S.poles.length, m = S.zeros.length;
    if (n > m) {
      const c = (S.poles.reduce((a, p) => a + p.re, 0) - S.zeros.reduce((a, z) => a + z.re, 0)) / (n - m);
      for (let k = 0; k < n - m; k++) S.asymptotes.push({ c, a: (2 * k + 1) * Math.PI / (n - m) });
    }

    let ext = 1;
    for (const z of S.poles.concat(S.zeros)) ext = Math.max(ext, Math.hypot(z.re, z.im));
    let far = ext;
    for (const b of S.branches) for (const p of b) far = Math.max(far, Math.hypot(p[0], p[1]));
    S.Rbase = Math.max(ext * 1.8, 8);
    S.zoom = 1;
    S.panX = 0; S.panY = 0;
    S.R = S.Rbase;
    S.fitPending = true;
    S.K = 1;
    const slider = $('rlK'), lab = $('rlKv');
    if (slider) slider.value = String(Math.round(1000 * (Math.log10(S.K) - Math.log10(KMIN)) / (Math.log10(KMAX) - Math.log10(KMIN))));
    if (lab) lab.textContent = 'K=' + fmt(S.K, 2);
  }

  function layout() {
    const R = S.R;
    return {
      X: (v) => CX + (v - S.panX) / R * HALF,
      Y: (v) => CY - (v - S.panY) / R * HALF,
    };
  }
  function niceStep(span) {
    const raw = span / 4, p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    const n = raw / p, k = n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10;
    return k * p;
  }

  function drawStatic() {
    const svg = $('rlSvg');
    if (!svg || !S.model) return;
    clear(svg);
    svg.setAttribute('viewBox', '0 0 ' + VB + ' ' + VB);
    const { X, Y } = layout();
    const x0 = CX - HALF, x1 = CX + HALF;
    const y0 = CY - HALF, y1 = CY + HALF;
    const defs = add(svg, 'defs', {});
    const cp = add(defs, 'clipPath', { id: 'rlClip' });
    add(cp, 'rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0 });

    const xmin = S.panX - S.R, xmax = S.panX + S.R;
    const ymin = S.panY - S.R, ymax = S.panY + S.R;
    const step = niceStep(2 * S.R);
    let t;
    for (let i = 0; ; i++) {
      t = Math.ceil(xmin / step) * step + i * step;
      if (t > xmax + step * 1e-6) break;
      add(svg, 'line', { x1: X(t), y1: y0, x2: X(t), y2: y1, class: 'rl-gridline' });
      if (Math.abs(t) > step * 1e-6) text(svg, X(t), y1 + 13, fmt(t, step < 1 ? 2 : 1), 'rl-ax');
    }
    for (let i = 0; ; i++) {
      t = Math.ceil(ymin / step) * step + i * step;
      if (t > ymax + step * 1e-6) break;
      add(svg, 'line', { x1: x0, y1: Y(t), x2: x1, y2: Y(t), class: 'rl-gridline' });
      if (Math.abs(t) > step * 1e-6) text(svg, x0 - 6, Y(t) + 3, fmt(t, step < 1 ? 2 : 1), 'rl-ax', 'end');
    }
    const ax = X(0), ay = Y(0);
    if (ax >= x0 && ax <= x1) add(svg, 'line', { x1: ax, y1: y0, x2: ax, y2: y1, class: 'rl-axis' });
    if (ay >= y0 && ay <= y1) add(svg, 'line', { x1: x0, y1: ay, x2: x1, y2: ay, class: 'rl-axis' });
    text(svg, x1 - 4, y0 + 12, 'Im', 'rl-ax', 'end');
    text(svg, x1, (ay >= y0 && ay <= y1 ? ay : y1) - 7, 'Re', 'rl-ax', 'end');

    const g = add(svg, 'g', { 'clip-path': 'url(#rlClip)' });

    /* 渐近线 */
    for (const as of S.asymptotes) {
      const L = S.R * 2.4;
      const dx = Math.cos(as.a) * L, dy = Math.sin(as.a) * L;
      add(g, 'line', {
        x1: X(as.c), y1: Y(0), x2: X(as.c + dx), y2: Y(dy),
        class: 'rl-asy',
      });
    }

    /* 分支 */
    for (const b of S.branches) {
      const d = b.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('');
      add(g, 'path', { d, class: 'rl-branch' });
    }

    /* 开环极点 / 零点 */
    for (const p of S.poles) {
      const c = add(g, 'circle', { cx: X(p.re), cy: Y(p.im), r: 4.6, class: 'rl-pole' });
      c.setAttribute('fill', '#d1372c');
    }
    for (const z of S.zeros) {
      const c = add(g, 'circle', { cx: X(z.re), cy: Y(z.im), r: 4.6, class: 'rl-zero' });
      c.setAttribute('fill', '#2e9e5b');
    }

    /* 分离点 */
    for (const b of S.breakaways.slice(0, 4)) {
      add(g, 'circle', { cx: X(b.s), cy: Y(0), r: 3, class: 'rl-break' });
    }
    if (S.breakaways.length) {
      const b0 = S.breakaways[0];
      text(svg, X(b0.s) - 6, Y(0) - 10, '分离点', 'rl-label', 'end');
    }

    /* 当前 K 的闭环极点放在单独组里，滑 K 时只重画这一层 */
    add(svg, 'g', { id: 'rlCurrent' });
    S.layout = { X, Y };
    drawCurrent();
  }

  function drawCurrent() {
    const g = $('rlCurrent');
    if (!g || !S.layout) return;
    const rs = sortRoots(clRoots(S.K));
    let maxAbs = 0;
    for (const r of rs) maxAbs = Math.max(maxAbs, Math.hypot(r.re, r.im));
    S.fitR = Math.max(S.Rbase, maxAbs * 1.22);
    S.outside = maxAbs > S.R * 1.02;
    if (S.fitPending) {
      S.fitPending = false;
      S.R = S.fitR;
      S.reflow = true;
      drawStatic();
      S.reflow = false;
      return;
    }
    clear(g);
    const cols = ['#e4572e', '#1f6fb4', '#c58a1a', '#7d4f9e'];
    rs.forEach((r, i) => {
      const c = add(g, 'circle', {
        cx: S.layout.X(r.re), cy: S.layout.Y(r.im), r: 5.4, class: 'rl-current',
      });
      c.setAttribute('fill', cols[i % cols.length]);
    });
    info(rs);
  }

  function info(rs) {
    const el = $('rlInfo');
    if (!el) return;
    const snap = (v) => (Math.abs(v) < 1e-6 ? 0 : v);
    const anyRight = rs.some((z) => snap(z.re) > 0);
    const anyAxis = rs.some((z) => snap(z.re) === 0);
    const stable = !anyRight && !anyAxis;
    const marginal = !anyRight && anyAxis;      // 极点落在虚轴/原点：临界稳定
    const shown = [];
    for (const z of rs) {
      if (z.im < -1e-7) continue;
      const re = snap(z.re), im = snap(Math.abs(z.im));
      shown.push(im === 0 ? fmt(re, 2) : fmt(re, 2) + '±' + fmt(im, 2) + 'j');
    }
    const eig = shown.join('，');
    const dom = rs.slice().sort((a, b) => b.re - a.re)[0];
    const osc = !!dom && Math.abs(dom.im) > 1e-7;
    const wn = osc ? Math.hypot(dom.re, dom.im) : NaN;
    const zeta = osc && wn ? -dom.re / wn : NaN;
    const cls = marginal ? 'ph-warn' : (stable ? 'ph-good' : 'ph-bad');
    const statTxt = marginal ? '临界稳定（极点落在虚轴/原点）'
      : (stable ? '闭环稳定' : '闭环不稳定');
    el.innerHTML =
      '<div class="rl-status ' + cls + '">K=' + fmt(S.K, 2) + ' · ' + statTxt + '</div>' +
      '<div class="ph-kv"><span>闭环极点</span><b>' + eig + '</b></div>' +
      '<div class="ph-kv"><span>主导 ζ / ωₙ</span><b>' + (osc ? fmt(zeta, 3) + ' / ' + fmt(wn, 3) + ' rad/s'
        : (dom ? '主导极点 ' + fmt(dom.re, 2) + '（实），ζ / ωₙ 不适用' : 'ζ / ωₙ 不适用')) + '</b></div>' +
      '<div class="ph-kv"><span>开环</span><b>' + S.poles.length + ' 极点 · ' + S.zeros.length + ' 零点</b></div>' +
      '<div class="ph-kv"><span>渐近线</span><b>' + (S.asymptotes.length ? S.asymptotes.length + ' 条 · 交点 ' + fmt(snapv(S.asymptotes[0].c), 2) : '无') + '</b></div>' +
      '<div class="ph-kv"><span>分离点</span><b>' + (S.breakaways.length ? fmt(snapv(S.breakaways[0].s), 2) : '无') + '</b></div>';
    if (S.outside) el.insertAdjacentHTML('beforeend','<div class="hint">当前极点超出视野，滚轮/二指缩小查看</div>');
    const lab = $('rlKv');
    if (lab) lab.textContent = 'K=' + fmt(S.K, 2);
  }

  function update(model) {
    const card = $('rlCard');
    if (!card) return;
    if (!model || !model.ol_num || !model.ol_den || model.ol_den.length < 3) {
      card.hidden = true; S.model = null; return;
    }
    S.model = model;
    build(model);
    card.hidden = false;
    drawStatic();
    const note = $('rlNote');
    if (note) note.textContent = '开环 ' + S.poles.length + ' 极点 / ' + S.zeros.length + ' 零点 · K = 0.01…1000 · 拖动 K 调增益，拖动空白平移';
  }

  function kToSlider(k) {
    return Math.round(1000 * (Math.log10(k) - Math.log10(KMIN)) / (Math.log10(KMAX) - Math.log10(KMIN)));
  }
  function setK(k, draw, fit) {
    S.K = Math.max(KMIN, Math.min(KMAX, k));
    const slider = $('rlK'), lab = $('rlKv');
    if (slider) slider.value = String(kToSlider(S.K));
    if (lab) lab.textContent = 'K=' + fmt(S.K, 2);
    if (draw) { if (fit) S.fitPending = true; drawCurrent(); }
  }

  function bind() {
    const slider = $('rlK'), lab = $('rlKv');
    if (slider) {
      slider.value = String(kToSlider(S.K));
      slider.addEventListener('input', () => {
        const t = (+slider.value || 0) / 1000;
        S.K = Math.pow(10, Math.log10(KMIN) + t * (Math.log10(KMAX) - Math.log10(KMIN)));
        if (lab) lab.textContent = 'K=' + fmt(S.K, 2);
        drawCurrent();
      });
    }
    const reset = $('rlReset');
    if (reset) {
      reset.addEventListener('click', () => {
        S.panX = 0; S.panY = 0;
        setK(1, true, true);
        S.R = S.fitR;
        drawStatic();
      });
    }
    const svg = $('rlSvg');
    if (svg) {
      const pts = new Map();
      let drag = null, pinch = null;
      const mid = () => {
        const arr = Array.from(pts.values());
        return { x: (arr[0].x + arr[1].x) / 2, y: (arr[0].y + arr[1].y) / 2 };
      };
      const dist = () => {
        const arr = Array.from(pts.values());
        return Math.hypot(arr[0].x - arr[1].x, arr[0].y - arr[1].y) || 1;
      };
      const zoomAt = (px, py, f) => {
        const x = S.panX + (2 * px - 1) * S.R;
        const y = S.panY + (1 - 2 * py) * S.R;
        const nR = Math.max(S.fitR / 10, Math.min(S.fitR * 10, S.R * f));
        S.panX = x - (2 * px - 1) * nR;
        S.panY = y - (1 - 2 * py) * nR;
        S.R = nR;
        drawStatic();
      };
      svg.addEventListener('pointerdown', (e) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        try { svg.setPointerCapture(e.pointerId); } catch (err) {}
        if (pts.size === 1) {
          const r = svg.getBoundingClientRect();
          drag = { id: e.pointerId, x: e.clientX, y: e.clientY,
                   px: S.panX, py: S.panY, w: r.width || r.height || 1 };
        } else if (pts.size === 2) {
          const r = svg.getBoundingClientRect();
          const m = mid();
          pinch = { d: dist(), px: (m.x - r.left) / r.width,
                    py: (m.y - r.top) / r.height, panX: S.panX, panY: S.panY, R: S.R };
          drag = null;
        }
        svg.classList.add('rl-drag');
        e.preventDefault();
      });
      svg.addEventListener('pointermove', (e) => {
        if (!pts.has(e.pointerId)) return;
        pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pts.size >= 2 && pinch) {
          const r = svg.getBoundingClientRect();
          const m = mid();
          const px = (m.x - r.left) / r.width, py = (m.y - r.top) / r.height;
          const nR = Math.max(S.fitR / 10, Math.min(S.fitR * 10, pinch.R * pinch.d / dist()));
          const x = pinch.panX + (2 * pinch.px - 1) * pinch.R;
          const y = pinch.panY + (1 - 2 * pinch.py) * pinch.R;
          S.R = nR;
          S.panX = x - (2 * px - 1) * nR;
          S.panY = y - (1 - 2 * py) * nR;
          drawStatic();
        } else if (drag && e.pointerId === drag.id) {
          const per = 2 * S.R / drag.w;
          S.panX = drag.px - (e.clientX - drag.x) * per;
          S.panY = drag.py + (e.clientY - drag.y) * per;
          drawStatic();
        }
      });
      const end = (e) => {
        pts.delete(e.pointerId);
        if (pts.size < 2) pinch = null;
        if (pts.size === 1) {
          const r = svg.getBoundingClientRect();
          const p = Array.from(pts.values())[0];
          drag = { id: Array.from(pts.keys())[0], x: p.x, y: p.y,
                   px: S.panX, py: S.panY, w: r.width || r.height || 1 };
        } else if (!pts.size) {
          drag = null;
          svg.classList.remove('rl-drag');
        }
        try { svg.releasePointerCapture(e.pointerId); } catch (err) {}
      };
      svg.addEventListener('pointerup', end);
      svg.addEventListener('pointercancel', end);
      svg.addEventListener('wheel', (e) => {
        e.preventDefault();
        const r = svg.getBoundingClientRect();
        zoomAt((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height,
               Math.exp(e.deltaY * 0.0015));
      }, { passive: false });
    }
  }

  window.RootLocus = { update, state: () => ({ R: S.R, panX: S.panX, panY: S.panY, K: S.K }) };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
