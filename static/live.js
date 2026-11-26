/* 实时联动工作台：Bode（精确/渐近）+ 闭环阶跃。
 * 依赖 window.LiveCore；只做预览，精确结果仍以 Python /api 为准。
 */
(function () {
  'use strict';
  const LC = window.LiveCore;
  if (!LC) return;
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const W = 460, H_BODE = 330, H_STEP = 300;
  const M = { l: 46, r: 10, t: 12 };

  const S = {
    model: null, baseNum: [], baseDen: [], gain: 1,
    bode: null, asy: null, step: null, met: null, cross: null,
    cursorW: null, cursorT: null, bodeCur: null, stepCur: null,
  };

  function add(parent, tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    parent.appendChild(e);
    return e;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function fmt(v, n) {
    if (v == null || !isFinite(v)) return '—';
    const a = Math.abs(v);
    if (a !== 0 && (a >= 1e4 || a < 1e-3)) return v.toExponential(1).replace('e+', 'e');
    return (+v).toFixed(n == null ? 3 : n).replace(/\.?0+$/, '');
  }
  function tickW(v) {
    if (v >= 1000) return (v / 1000).toFixed(v >= 10000 ? 0 : 1).replace('.0', '') + 'k';
    if (v >= 1) return String(Math.round(v));
    return String(+v.toFixed(3));
  }
  function linePath(pts) {
    return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
  }
  function text(parent, x, y, s, cls, anchor) {
    const t = add(parent, 'text', { x: x, y: y, class: cls || 'live-ax', 'text-anchor': anchor || 'start' });
    t.textContent = s;
    return t;
  }
  function clipText(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  /* ---------- Bode ---------- */
  function drawBode() {
    const svg = $('bodeLive');
    if (!svg || !S.bode) return;
    clear(svg);
    const cw = svg.getBoundingClientRect().width || 460;
    const Wd = cw < 400 ? 360 : W;
    const ML = cw < 400 ? 34 : M.l, MR = M.r;
    svg.setAttribute('viewBox', '0 0 ' + Wd + ' ' + H_BODE);
    S.layout = { W: Wd, l: ML, r: MR };
    const b = S.bode, w = b.w, n = w.length;
    const x0 = ML, x1 = Wd - MR;
    const dbT = M.t + 8, dbB = 196, phT = 214, phB = 284;
    const lw = Math.log(w[0]), lr = Math.log(w[n - 1]) - lw;
    const X = (ww) => x0 + (Math.log(ww) - lw) / lr * (x1 - x0);

    let dbMin = Infinity, dbMax = -Infinity;
    for (let i = 0; i < n; i++) {
      dbMin = Math.min(dbMin, b.db[i], S.asy[i]);
      dbMax = Math.max(dbMax, b.db[i], S.asy[i]);
    }
    dbMin = Math.max(-140, Math.min(-40, Math.floor(dbMin / 20) * 20));
    dbMax = Math.max(20, Math.min(80, Math.ceil(dbMax / 20) * 20));
    const Y = (v) => dbB - (v - dbMin) / (dbMax - dbMin) * (dbB - dbT);

    let phMin = 0, phMax = 0;
    for (let i = 0; i < n; i++) { phMin = Math.min(phMin, b.ph[i]); phMax = Math.max(phMax, b.ph[i]); }
    phMin = Math.max(-360, Math.floor(phMin / 90) * 90);
    phMax = Math.min(90, Math.ceil(phMax / 90) * 90);
    if (phMax - phMin < 90) phMin = phMax - 180;
    const YP = (v) => phB - (v - phMin) / (phMax - phMin) * (phB - phT);

    /* 网格：十倍频程 */
    const k0 = Math.ceil(Math.log10(w[0])), k1 = Math.floor(Math.log10(w[n - 1]));
    const narrow = (svg.getBoundingClientRect().width || 460) < 400;
    for (let k = k0; k <= k1; k++) {
      const ww = Math.pow(10, k), x = X(ww);
      add(svg, 'line', { x1: x, y1: dbT, x2: x, y2: phB, class: 'live-grid' });
      if ((k1 - k0 <= 6 && (!narrow || (k - k0) % 2 === 0)) || (!narrow && k1 - k0 <= 8)) {
        const anchor = k === k0 ? 'start' : (x > x1 - 10 ? 'end' : 'middle');
        text(svg, x, phB + 14, '10' + sup(k), 'live-ax', anchor);
      }
    }
    for (let v = dbMin; v <= dbMax + 1e-9; v += 20) {
      const y = Y(v);
      add(svg, 'line', { x1: x0, y1: y, x2: x1, y2: y, class: 'live-grid' });
      text(svg, x0 - 7, y + 3, String(v), 'live-ax', 'end');
    }
    for (let v = phMin; v <= phMax + 1e-9; v += 90) {
      const y = YP(v);
      add(svg, 'line', { x1: x0, y1: y, x2: x1, y2: y, class: 'live-grid' });
      text(svg, x0 - 7, y + 3, String(v), 'live-ax', 'end');
    }
    add(svg, 'line', { x1: x0, y1: Y(0), x2: x1, y2: Y(0), class: 'live-zero' });

    const exact = [], asy = [], ph = [];
    for (let i = 0; i < n; i++) {
      exact.push([X(w[i]), Y(b.db[i])]);
      asy.push([X(w[i]), Y(S.asy[i])]);
      ph.push([X(w[i]), YP(b.ph[i])]);
    }
    add(svg, 'path', { d: linePath(asy), class: 'live-asy' });
    add(svg, 'path', { d: linePath(exact), class: 'live-exact' });
    add(svg, 'path', { d: linePath(ph), class: 'live-phase' });

    /* 交点标记 */
    if (S.cross && isFinite(S.cross.wc) && S.cross.wc > w[0] && S.cross.wc < w[n - 1]) {
      const x = X(S.cross.wc);
      add(svg, 'line', { x1: x, y1: dbT, x2: x, y2: phB, class: 'live-mark' });
      text(svg, x + 3, dbT + 10, 'ωc=' + fmt(S.cross.wc, 2), 'live-marktx');
    }
    text(svg, x1, dbT + 10, 'dB', 'live-ax', 'end');
    text(svg, x1, phT + 10, '°', 'live-ax', 'end');
    text(svg, (x0 + x1) / 2, H_BODE - 4, 'ω (rad/s)', 'live-axis', 'middle');

    const g = add(svg, 'g', { class: 'live-cursor', visibility: 'hidden' });
    const cx = add(g, 'line', { x1: 0, y1: dbT, x2: 0, y2: phB, class: 'live-cross' });
    const cd = add(g, 'circle', { cx: 0, cy: 0, r: 3.2, class: 'live-dot' });
    const cp = add(g, 'circle', { cx: 0, cy: 0, r: 3.2, class: 'live-dot' });
    S.bodeCur = { g, cx, cd, cp, X, Y, YP, w };

    if (S.cursorW) placeBode(S.cursorW); else defaultBode();
  }

  function sup(k) {
    const map = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
    return String(k).split('').map((c) => map[c] || c).join('');
  }

  function defaultBode() {
    const read = $('bodeRead');
    if (!read) return;
    const c = S.cross || {};
    const t = '移动/拖动查看读数　ω<sub>c</sub>=' + fmt(c.wc, 2) + ' rad/s　γ=' + fmt(c.pm, 1) + '°';
    read.innerHTML = t;
    if (S.bodeCur) S.bodeCur.g.setAttribute('visibility', 'hidden');
  }

  function placeBode(ww) {
    const st = S.bodeCur;
    if (!st) return;
    const i = LC.nearestIndex(st.w, ww);
    const w = st.w[i], db = S.bode.db[i], ph = S.bode.ph[i];
    const x = st.X(w);
    st.cx.setAttribute('x1', x); st.cx.setAttribute('x2', x);
    st.cd.setAttribute('cx', x); st.cd.setAttribute('cy', st.Y(db));
    st.cp.setAttribute('cx', x); st.cp.setAttribute('cy', st.YP(ph));
    st.g.setAttribute('visibility', 'visible');
    const read = $('bodeRead');
    if (read) read.innerHTML = 'ω=' + fmt(w, 3) + ' rad/s　|L|=' + fmt(db, 2) + ' dB　∠L=' + fmt(ph, 1) + '°';
    window.dispatchEvent(new CustomEvent('livefreq', { detail: { w: w, gain: S.gain } }));
  }

  /* ---------- 阶跃 ---------- */
  function drawStep() {
    const svg = $('stepLive');
    if (!svg || !S.step) return;
    clear(svg);
    const cw = svg.getBoundingClientRect().width || 460;
    const Wd = cw < 400 ? 360 : W;
    const ML = cw < 400 ? 34 : M.l, MR = M.r;
    svg.setAttribute('viewBox', '0 0 ' + Wd + ' ' + H_STEP);
    S.layout = { W: Wd, l: ML, r: MR };
    const { t, y, tEnd } = S.step;
    const x0 = ML, x1 = Wd - MR, yT = M.t + 8, yB = 246;
    let yMin = Infinity, yMax = -Infinity;
    for (let i = 0; i < y.length; i++) { yMin = Math.min(yMin, y[i]); yMax = Math.max(yMax, y[i]); }
    yMin = Math.min(0, yMin); yMax = Math.max(1.02, yMax);
    const pad = (yMax - yMin) * 0.08 || 0.1;
    yMin -= pad; yMax += pad;
    const X = (tt) => x0 + tt / tEnd * (x1 - x0);
    const Y = (v) => yB - (v - yMin) / (yMax - yMin) * (yB - yT);

    for (let i = 0; i <= 5; i++) {
      const x = x0 + i / 5 * (x1 - x0);
      add(svg, 'line', { x1: x, y1: yT, x2: x, y2: yB, class: 'live-grid' });
      text(svg, x, yB + 14, fmt(i / 5 * tEnd, 2) + 's', 'live-ax', 'middle');
    }
    const rawStep = (yMax - yMin) / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const nstep = [1, 2, 2.5, 5, 10].find((k) => k * mag >= rawStep) * mag;
    for (let v = Math.ceil(yMin / nstep) * nstep; v <= yMax + 1e-9; v += nstep) {
      const y = Y(v);
      add(svg, 'line', { x1: x0, y1: y, x2: x1, y2: y, class: 'live-grid' });
      text(svg, x0 - 7, y + 3, fmt(v, 2), 'live-ax', 'end');
    }
    const ss = S.met ? S.met.ss : 1;
    if (!S.marginal) {
      add(svg, 'line', { x1: x0, y1: Y(ss), x2: x1, y2: Y(ss), class: 'live-asy' });
    }
    const pts = [];
    for (let i = 0; i < t.length; i++) pts.push([X(t[i]), Y(y[i])]);
    add(svg, 'path', { d: linePath(pts), class: 'live-exact' });
    text(svg, x0, yT - 4, 'c(t)', 'live-axis', 'start');
    text(svg, (x0 + x1) / 2, H_STEP - 4, 't (s)', 'live-axis', 'middle');

    const g = add(svg, 'g', { class: 'live-cursor', visibility: 'hidden' });
    const cx = add(g, 'line', { x1: 0, y1: yT, x2: 0, y2: yB, class: 'live-cross' });
    const cd = add(g, 'circle', { cx: 0, cy: 0, r: 3.2, class: 'live-dot' });
    S.stepCur = { g, cx, cd, X, Y };
    defaultStep();
  }

  function defaultStep() {
    const read = $('stepRead');
    if (!read) return;
    if (S.stepCur) S.stepCur.g.setAttribute('visibility', 'hidden');
    if (S.marginal) {
      read.innerHTML = '⚠ 临界稳定：阶跃响应为斜坡/等幅振荡，σ / t<sub>p</sub> / t<sub>s</sub> / y(∞) 不定义';
      return;
    }
    const m = S.met || {};
    read.innerHTML = 'σ=' + fmt(m.sigma, 2) + '%　t<sub>p</sub>=' + fmt(m.tp * 1000, 1) +
      ' ms　t<sub>s</sub>=' + fmt(m.ts * 1000, 1) + ' ms　y(∞)=' + fmt(m.ss, 4);
  }

  function placeStep(tt) {
    const st = S.stepCur;
    if (!st) return;
    const t = S.step.t;
    let i = 0, d = Infinity;
    for (let k = 0; k < t.length; k++) { const dd = Math.abs(t[k] - tt); if (dd < d) { d = dd; i = k; } }
    const x = st.X(t[i]);
    st.cx.setAttribute('x1', x); st.cx.setAttribute('x2', x);
    st.cd.setAttribute('cx', x); st.cd.setAttribute('cy', st.Y(S.step.y[i]));
    st.g.setAttribute('visibility', 'visible');
    const read = $('stepRead');
    if (read) read.innerHTML = 't=' + fmt(t[i] * 1000, 1) + ' ms　c=' + fmt(S.step.y[i], 4);
  }

  /* ---------- 计算与同步 ---------- */
  function compute() {
    if (!S.model) return;
    const num = LC.polyscale(S.baseNum, S.gain);
    const den = S.baseDen;
    S.bode = LC.bode(num, den, 520);
    S.asy = LC.asymptote(num, den, S.bode.w);
    S.cross = LC.cross(S.bode);
    const cl = LC.closedLoop(num, den);
    S.step = LC.stepResponse(cl.num, cl.den, 1100);
    S.met = LC.stepMetrics(S.step.t, S.step.y);
    /* 临界稳定（极点落在虚轴/原点）：响应为斜坡或等幅振荡，时域指标不定义 */
    S.marginal = !!S.model.marginal;
    drawBode();
    drawStep();
    note();
    window.dispatchEvent(new CustomEvent('livefreq', { detail: { w: S.cursorW || (S.cross && S.cross.wc) || 1, gain: S.gain } }));
  }

  function note() {
    const el = $('liveNote');
    if (!el) return;
    let s = S.marginal
      ? '⚠ 闭环临界稳定（极点落在虚轴/原点）· 阶跃响应不收敛，时域指标不显示'
      : '连续线性 · 单位负反馈 · 拖动 K 或曲线实时预览';
    if (S.gain !== 1) s = '预览增益 ×' + S.gain.toFixed(2) + '（仅本卡，不改输入框）'
      + (S.marginal ? ' · ⚠ 临界稳定' : '');
    if (S.gain === 1 && S.model.wc && isFinite(S.model.wc) && S.cross && isFinite(S.cross.wc)) {
      const rel = Math.abs(S.cross.wc - S.model.wc) / Math.max(1e-9, S.model.wc);
      if (rel < 2e-3) s += ' · 已与内核校验';
    }
    el.textContent = s;
  }

  let pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; compute(); });
  }

  function bind() {
    const slider = $('liveK'), label = $('liveKv');
    if (slider) {
      slider.addEventListener('input', () => {
        S.gain = +slider.value || 1;
        if (label) label.textContent = '×' + S.gain.toFixed(2);
        window.dispatchEvent(new CustomEvent('livegain', { detail: { gain: S.gain } }));
        schedule();
      });
    }
    const bode = $('bodeLive');
    if (bode) {
      bode.addEventListener('pointermove', (e) => {
        if (!S.bode) return;
        const r = bode.getBoundingClientRect();
        const L = S.layout || { W: W, l: M.l, r: M.r };
        const x = (e.clientX - r.left) / r.width * L.W;
        const b = S.bode, w0 = b.w[0], w1 = b.w[b.w.length - 1];
        if (x < L.l || x > L.W - L.r) return;
        const frac = (x - L.l) / (L.W - L.r - L.l);
        S.cursorW = Math.exp(Math.log(w0) + frac * (Math.log(w1) - Math.log(w0)));
        placeBode(S.cursorW);
      });
      bode.addEventListener('pointerleave', () => { S.cursorW = null; defaultBode(); });
      bode.addEventListener('pointerdown', (e) => {
        try { bode.setPointerCapture(e.pointerId); } catch (_) {}
      });
    }
    const step = $('stepLive');
    if (step) {
      step.addEventListener('pointermove', (e) => {
        if (!S.step) return;
        const r = step.getBoundingClientRect();
        const L = S.layout || { W: W, l: M.l, r: M.r };
        const x = (e.clientX - r.left) / r.width * L.W;
        if (x < L.l || x > L.W - L.r) return;
        S.cursorT = (x - L.l) / (L.W - L.r - L.l) * S.step.tEnd;
        placeStep(S.cursorT);
      });
      step.addEventListener('pointerleave', () => { S.cursorT = null; defaultStep(); });
    }
  }

  function update(model) {
    const card = $('liveCard');
    if (!card) return;
    if (!model || !model.ol_num || !model.ol_den || !model.ol_num.length) {
      card.hidden = true;
      S.model = null;
      return;
    }
    card.hidden = false;
    S.model = model;
    S.baseNum = model.ol_num.slice();
    S.baseDen = model.ol_den.slice();
    S.gain = 1;
    S.cursorW = null; S.cursorT = null;
    const slider = $('liveK'), label = $('liveKv');
    if (slider) slider.value = '1';
    if (label) label.textContent = '×1.00';
    compute();
  }

  window.LiveWorkbench = {
    update,
    state: () => ({ gain: S.gain, w: S.cursorW || (S.cross && S.cross.wc) || 1, wc: S.cross && S.cross.wc, model: S.model }),
  };
  let rt = null;
  window.addEventListener('resize', () => {
    if (!S.model) return;
    clearTimeout(rt);
    rt = setTimeout(() => { drawBode(); drawStep(); }, 120);
  });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
