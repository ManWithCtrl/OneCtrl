/* M4：正弦稳态（频域 → 时域）与主导极点近似（时域 → 模态）。
 * 依赖 LiveCore；与实时联动共享增益与 Bode 游标频率；导出为自包含 HTML 报告。
 */
(function () {
  'use strict';
  const LC = window.LiveCore;
  if (!LC) return;
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const PI = Math.PI;

  const S = {
    model: null, gain: 1, w: 1, tf: 'cl', amp: 1,
    baseNum: [], baseDen: [], sine: null, actual: null, actualMet: null,
    approx: null, approxMet: null, dom: null,
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
  function text(parent, x, y, s, cls, anchor) {
    const t = add(parent, 'text', { x: x, y: y, class: cls || 'live-ax', 'text-anchor': anchor || 'start' });
    t.textContent = s;
    return t;
  }
  function path(pts) {
    return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
  }
  function cpx(xr, xi) { return LC.C(xr, xi); }
  function H(num, den, w) {
    const s = cpx(0, w);
    return LC.cdiv(LC.polyval(num, s), LC.polyval(den, s));
  }
  function interp(t, y, tt) {
    if (tt <= t[0]) return y[0];
    if (tt >= t[t.length - 1]) return y[y.length - 1];
    let lo = 0, hi = t.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (t[mid] <= tt) lo = mid; else hi = mid;
    }
    const f = (tt - t[lo]) / (t[hi] - t[lo] || 1);
    return y[lo] + f * (y[hi] - y[lo]);
  }
  function filtered(rows) {
    const out = [];
    for (const r of rows) {
      if (r.im < -1e-7) continue;
      out.push(r);
    }
    return out;
  }

  function tfPair() {
    const num = LC.polyscale(S.baseNum, S.gain);
    const den = S.baseDen.slice();
    return { num, den, cl: LC.closedLoop(num, den) };
  }

  /* ---------- 正弦稳态 ---------- */
  function sineCompute() {
    const p = tfPair();
    const tf = S.tf === 'cl' ? p.cl : p;
    const w = Math.max(1e-6, S.w);
    const h = H(tf.num, tf.den, w);
    const mag = LC.cabs(h);
    const ph = LC.carg(h) * 180 / PI;
    const rs = LC.roots(tf.den);
    const marginal = rs.some((r) => Math.abs(r.re) <= 1e-9);
    const stable = !marginal && rs.every((r) => r.re < -1e-9);
    const T = 2 * PI / w;
    return { w, mag, ph, amp: S.amp, out: S.amp * mag, T, stable, marginal, h, tf: S.tf };
  }

  function drawSine() {
    const svg = $('m4Sine');
    if (!svg || !S.sine) return;
    clear(svg);
    const cw = svg.getBoundingClientRect().width || 460;
    const Wd = cw < 400 ? 360 : 640;
    const Hh = 260, ML = cw < 400 ? 42 : 52, MR = 12, MT = 14, MB = 28;
    svg.setAttribute('viewBox', '0 0 ' + Wd + ' ' + Hh);
    const s = S.sine;
    const tEnd = 2 * s.T;
    const amp = Math.max(s.amp, s.stable ? s.out : 0, 1e-6) * 1.22;
    const x0 = ML, x1 = Wd - MR, y0 = MT, y1 = Hh - MB;
    const X = (tt) => x0 + tt / tEnd * (x1 - x0);
    const Y = (v) => (y0 + y1) / 2 - v / amp * (y1 - y0) / 2;

    for (let i = 0; i <= 4; i++) {
      const x = x0 + i / 4 * (x1 - x0);
      add(svg, 'line', { x1: x, y1: y0, x2: x, y2: y1, class: 'live-grid' });
      const tt = i / 4 * tEnd;
      text(svg, x, y1 + 14, fmt(tt, 3) + 's', 'live-ax', 'middle');
    }
    for (let i = 0; i <= 4; i++) {
      const v = amp - i / 2 * amp;
      const y = Y(v);
      add(svg, 'line', { x1: x0, y1: y, x2: x1, y2: y, class: 'live-grid' });
      text(svg, x0 - 6, y + 3, fmt(v, 2), 'live-ax', 'end');
    }
    add(svg, 'line', { x1: x0, y1: Y(0), x2: x1, y2: Y(0), class: 'live-zero' });

    const n = 240, ptsIn = [], ptsOut = [];
    for (let i = 0; i <= n; i++) {
      const tt = i / n * tEnd;
      const u = s.amp * Math.sin(s.w * tt);
      ptsIn.push([X(tt), Y(u)]);
      if (s.stable) ptsOut.push([X(tt), Y(s.out * Math.sin(s.w * tt + s.ph * PI / 180))]);
    }
    add(svg, 'path', { d: path(ptsIn), class: 'live-exact m4-in' });
    if (s.stable && ptsOut.length) add(svg, 'path', { d: path(ptsOut), class: 'm4-out' });

    text(svg, x1, y0 + 10, 'y', 'live-axis', 'end');
    text(svg, (x0 + x1) / 2, Hh - 3, 't (s)', 'live-axis', 'middle');

    const wv = $('m4Wv');
    if (wv) wv.textContent = 'ω=' + fmt(s.w, 3) + ' rad/s';
    const read = $('m4SineRead');
    if (read) {
      if (s.marginal) {
        read.innerHTML = '闭环临界稳定（极点落在虚轴/原点）：不存在稳态正弦响应（仍显示输入波形）。';
      } else if (!s.stable) {
        read.innerHTML = '该传递函数闭环不稳定，不存在稳态正弦响应（仍显示输入波形）。';
      } else {
        read.innerHTML = '|G|=' + fmt(s.mag, 3) + '（' + fmt(20 * Math.log10(Math.max(1e-12, s.mag)), 2) + ' dB）　∠G=' +
          fmt(s.ph, 1) + '°　A<sub>out</sub>=' + fmt(s.out, 3) + '　T=' + fmt(s.T, 3) + ' s';
      }
    }
  }

  /* ---------- 主导极点近似 ---------- */
  function dominant(clDen) {
    const rs = LC.roots(clDen);
    // 有根压在虚轴/原点上时报「临界」，二阶主导极点近似在这里没有意义
    if (rs.some((r) => Math.abs(r.re) <= 1e-9)) {
      return { type: 'marginal', roots: rs };
    }
    const cx = rs.filter((r) => r.im > 1e-6).sort((a, b) => b.re - a.re)[0];
    if (cx) {
      const wn = Math.hypot(cx.re, cx.im);
      return {
        type: 'complex', roots: [cx, cpx(cx.re, -cx.im)], sigma: cx.re, wd: cx.im,
        wn, zeta: -cx.re / wn, a1: -2 * cx.re, a2: wn * wn,
      };
    }
    const real = rs.filter((r) => Math.abs(r.im) < 1e-6).sort((a, b) => b.re - a.re);
    if (real.length >= 2) {
      const p1 = real[0].re, p2 = real[1].re;
      const a1 = -(p1 + p2), a2 = p1 * p2;
      const wn = Math.sqrt(Math.max(0, a2));
      return {
        type: 'real', roots: [cpx(p1, 0), cpx(p2, 0)], sigma: p1, wd: 0,
        wn, zeta: wn ? -a1 / (2 * wn) : NaN, a1, a2,
      };
    }
    return null;
  }

  function domCompute() {
    const p = tfPair();
    const actual = LC.stepResponse(p.cl.num, p.cl.den, 900);
    const met = LC.stepMetrics(actual.t, actual.y);
    const d = dominant(p.cl.den);
    let approx = null, amet = null, rms = null;
    if (d && d.type !== 'marginal') {
      approx = LC.stepResponse([d.a2], [1, d.a1, d.a2], 900);
      amet = LC.stepMetrics(approx.t, approx.y);
      let se = 0;
      for (let i = 0; i < actual.t.length; i++) {
        const e = actual.y[i] - interp(approx.t, approx.y, actual.t[i]);
        se += e * e;
      }
      rms = Math.sqrt(se / actual.t.length);
    }
    return { actual, met, d, approx, amet, rms, zeros: LC.roots(p.cl.num) };
  }

  function drawDom() {
    const svg = $('m4Dom');
    if (!svg || !S.actual) return;
    clear(svg);
    const cw = svg.getBoundingClientRect().width || 460;
    const Wd = cw < 400 ? 360 : 640;
    const Hh = 260, ML = cw < 400 ? 42 : 52, MR = 12, MT = 14, MB = 28;
    svg.setAttribute('viewBox', '0 0 ' + Wd + ' ' + Hh);
    const a = S.actual, ap = S.approx;
    const x0 = ML, x1 = Wd - MR, y0 = MT, y1 = Hh - MB;
    const tEnd = a.tEnd;
    let yMax = 1.05;
    for (let i = 0; i < a.y.length; i++) yMax = Math.max(yMax, a.y[i]);
    if (ap) for (let i = 0; i < ap.y.length; i++) yMax = Math.max(yMax, ap.y[i]);
    yMax *= 1.08;
    const X = (tt) => x0 + tt / tEnd * (x1 - x0);
    const Y = (v) => y1 - v / yMax * (y1 - y0);

    for (let i = 0; i <= 5; i++) {
      const x = x0 + i / 5 * (x1 - x0);
      add(svg, 'line', { x1: x, y1: y0, x2: x, y2: y1, class: 'live-grid' });
      text(svg, x, y1 + 14, fmt(i / 5 * tEnd, 2) + 's', 'live-ax', 'middle');
    }
    const raw = yMax / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].find((k) => k * mag >= raw) * mag;
    for (let v = 0; v <= yMax + 1e-9; v += step) {
      const y = Y(v);
      add(svg, 'line', { x1: x0, y1: y, x2: x1, y2: y, class: 'live-grid' });
      text(svg, x0 - 6, y + 3, fmt(v, 2), 'live-ax', 'end');
    }
    add(svg, 'line', { x1: x0, y1: Y(1), x2: x1, y2: Y(1), class: 'live-zero' });
    add(svg, 'path', { d: path(a.t.map((tt, i) => [X(tt), Y(a.y[i])])), class: 'live-exact' });
    if (ap) add(svg, 'path', { d: path(a.t.map((tt) => [X(tt), Y(interp(ap.t, ap.y, tt))])), class: 'm4-approx' });
    text(svg, x1, y0 + 10, 'c(t)', 'live-axis', 'end');
    text(svg, (x0 + x1) / 2, Hh - 3, 't (s)', 'live-axis', 'middle');

    const rd = $('m4DomRead');
    if (!rd) return;
    const d = S.dom;
    if (d && d.type === 'marginal') {
      rd.innerHTML = '闭环临界稳定（极点落在虚轴/原点）：不存在可用的二阶主导极点近似，只画实际闭环节跃响应。';
      return;
    }
    if (!d) { rd.textContent = '当前闭环没有可用的二阶主导对。'; return; }
    const er = S.rms != null ? S.rms / Math.max(1e-9, 1) * 100 : NaN;
    rd.innerHTML = '主导' + (d.type === 'complex' ? '共轭对' : '实极点对') + '　σ=' + fmt(d.sigma, 3) +
      '　ζ=' + fmt(d.zeta, 3) + '　ω<sub>n</sub>=' + fmt(d.wn, 3) + ' rad/s<br>' +
      '实际 σ%=' + fmt(S.actualMet.sigma, 1) + '，近似 σ%=' + fmt(S.approxMet.sigma, 1) +
      '　实际 t<sub>s</sub>=' + fmt(S.actualMet.ts * 1000, 0) + ' ms，近似 t<sub>s</sub>=' + fmt(S.approxMet.ts * 1000, 0) + ' ms　RMS=' + fmt(er, 2) + '%<br>' +
      '闭环零点：' + (S.zeros && S.zeros.length ? S.zeros.slice(0, 4).map((z) => fmt(z.re, 2) + (Math.abs(z.im) > 1e-6 ? '±' + fmt(Math.abs(z.im), 2) + 'j' : '')).join('，') : '无') +
      '（与主导极点同量级时二阶近似偏差大）';
  }

  function note() {
    const el = $('m4Note');
    if (!el) return;
    el.textContent = S.gain === 1
      ? '拖动上方 Bode 游标，正弦稳态随频率变化；另一栏用主导极点近似对照阶跃。'
      : '预览增益 ×' + S.gain.toFixed(2) + '（仅本卡，不改输入框）';
  }

  function compute() {
    if (!S.model) return;
    S.sine = sineCompute();
    const dd = domCompute();
    S.actual = dd.actual; S.actualMet = dd.met;
    S.approx = dd.approx; S.approxMet = dd.amet; S.dom = dd.d; S.rms = dd.rms;
    S.zeros = dd.zeros || [];
    drawSine();
    drawDom();
    note();
  }

  let pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; compute(); });
  }

  function bind() {
    const amp = $('m4Amp');
    if (amp) amp.addEventListener('input', () => {
      S.amp = Math.max(0.01, +amp.value || 1);
      if (S.sine) { S.sine.amp = S.amp; S.sine.out = S.amp * S.sine.mag; drawSine(); }
    });
    const tf = $('m4Tf');
    if (tf) tf.addEventListener('change', () => { S.tf = tf.value; schedule(); });
    const ex = $('m4Export');
    if (ex) ex.addEventListener('click', exportReport);
    window.addEventListener('livefreq', (e) => {
      if (!S.model) return;
      S.w = Math.max(1e-6, (e.detail && e.detail.w) || S.w);
      S.gain = (e.detail && e.detail.gain) || S.gain;
      schedule();
    });
    window.addEventListener('livegain', (e) => {
      if (!S.model) return;
      S.gain = (e.detail && e.detail.gain) || S.gain;
      schedule();
    });
    window.addEventListener('resize', () => {
      if (!S.model) return;
      clearTimeout(bind._rt);
      bind._rt = setTimeout(() => { drawSine(); drawDom(); }, 120);
    });
  }

  /* ---------- 报告导出 ---------- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  function reportHtml() {
    const j = window.__lastResult;
    if (!j) return null;
    const now = new Date();
    const name = '控制校正验算报告-' + now.toISOString().slice(0, 16).replace(/[-:T]/g, '');
    const clean = (v) => String(v == null ? '' : v).replace(/<[^>]*>/g, '');
    const numv = (v) => {
      if (v == null || v === '') return '—';
      const n = Number(v);
      return isFinite(n) ? fmt(n, 4) : esc(v);
    };
    const rows = (j.tiles || []).map((t) => `<tr><td>${esc(clean(t.label))}${t.unit ? ' (' + esc(clean(t.unit).trim()) + ')' : ''}</td><td>${numv(t.before)}</td><td>${numv(t.after)}</td></tr>`).join('');
    const frows = ((j.formula && j.formula.rows) || []).map((r) => `<div class="fr"><div class="fl">${esc(r.label)}</div><div class="fm">${r.math || ''}</div><div class="fn">${esc(r.note || '')}</div></div>`).join('');
    const s = S.sine || {}, d = S.dom || {}, am = S.actualMet || {}, pm = S.approxMet || {};
    return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(name)}</title>
<style>body{overflow-x:hidden;font-family:"Noto Sans CJK SC","Microsoft YaHei",sans-serif;max-width:880px;margin:32px auto;padding:0 20px;color:#172033;line-height:1.6}
h1{font-size:24px}h2{font-size:17px;margin-top:28px;border-bottom:1px solid #dfe6ef;padding-bottom:6px}h3{font-size:14px;margin:18px 0 6px}
table{border-collapse:collapse;width:100%;font-size:13px;table-layout:fixed}td,th{border:1px solid #dfe6ef;padding:6px 8px;text-align:left;word-break:break-word}th{background:#f3f6fa}
.fr{display:grid;grid-template-columns:200px minmax(0,1fr);gap:4px 14px;border-bottom:1px dashed #e6ecf4;padding:8px 0;min-width:0}.fl{font-weight:600;font-size:12px;line-height:1.5}.fm{font-size:16px;overflow-x:auto;min-width:0}.fn{grid-column:2;color:#68758a;font-size:12px}
pre{background:#f6f8fb;padding:10px;white-space:pre-wrap;font-size:12px}.meta{color:#68758a;font-size:12px}.math{font-size:18px}
@media(max-width:600px){.fr{grid-template-columns:1fr}.fn{grid-column:1}}@media print{body{margin:0}h2{page-break-after:avoid}}</style></head><body>
<h1>控制校正验算报告</h1><div class="meta">生成时间：${esc(now.toLocaleString('zh-CN'))}　模式：${esc(j.mode || '—')}</div>
<h2>输入</h2><pre>${esc((j.formula && j.formula.src) || '')}</pre>
<h2>指标</h2><table><tr><th>指标</th><th>校正前</th><th>校正后</th></tr>${rows}</table>
${frows ? `<h2>公式回显</h2>${frows}` : ''}
<h2>频域 → 正弦稳态</h2><p>ω=${fmt(s.w, 4)} rad/s，|G|=${fmt(s.mag, 4)}，∠G=${fmt(s.ph, 2)}°，A_out=${fmt(s.out, 4)}，T=${fmt(s.T, 4)} s</p>
<h2>时域 → 主导极点</h2><p>${d.type === 'complex' ? '共轭对' : '实极点对'}：σ=${fmt(d.sigma, 4)}，ζ=${fmt(d.zeta, 3)}，ωn=${fmt(d.wn, 4)} rad/s；实际 σ%=${fmt(am.sigma, 2)}，t_s=${fmt(am.ts * 1000, 1)} ms；近似 σ%=${fmt(pm.sigma, 2)}，t_s=${fmt(pm.ts * 1000, 1)} ms；拟合 RMS=${fmt(S.rms, 4)}${S.zeros && S.zeros.length ? '；闭环零点 ' + S.zeros.slice(0, 4).map((z) => fmt(z.re, 2) + (Math.abs(z.im) > 1e-6 ? '±' + fmt(Math.abs(z.im), 2) + 'j' : '')).join('、') : ''}</p>
<h2>服务端文字结果</h2><pre>${esc(j.text || '')}</pre>
<div class="meta">由控制校正验算器生成；精确指标以服务端计算为准。</div></body></html>`;
  }
  function exportReport() {
    const html = reportHtml();
    const el = $('m4Note');
    if (!html) { if (el) el.textContent = '请先点“开始分析”，成功后再导出。'; return; }
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (html.match(/<title>([^<]+)/) || [])[1] + '.html';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  function update(model) {
    const card = $('m4Card');
    if (!card) return;
    if (!model || !model.ol_num || !model.ol_den || !model.cl_den || model.cl_den.length < 3) {
      card.hidden = true; S.model = null; return;
    }
    card.hidden = false;
    S.model = model;
    S.baseNum = model.ol_num.slice();
    S.baseDen = model.ol_den.slice();
    S.gain = 1;
    const st = window.LiveWorkbench && window.LiveWorkbench.state ? window.LiveWorkbench.state() : null;
    S.w = st && st.w ? st.w : (model.wc || 1);
    S.tf = $('m4Tf') ? $('m4Tf').value : 'cl';
    S.amp = $('m4Amp') ? Math.max(0.01, +$('m4Amp').value || 1) : 1;
    compute();
  }

  window.M4Workbench = { update };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
