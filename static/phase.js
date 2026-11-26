/* 相平面工作台：闭环主导二阶近似 + 矢量场 + 可点击轨迹。
 * 只做教学/直觉预览；精确指标仍以服务端为准。
 */
(function () {
  'use strict';
  const LC = window.LiveCore;
  if (!LC) return;
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);
  const VB = 360;                 // viewBox 宽高
  const CX = 180, CY = 156, HALF = 138;

  const S = {
    model: null, a1: 0, a2: 1, wn: 1, R: 2.5, type: '', stable: true,
    custom: [], roots: null, order: 0, layout: null,
    baseNum: null, baseDen: null, gain: 1, raf: 0, sys: 'cl',
  };

  function add(parent, tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    parent.appendChild(e);
    return e;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function fmt(v, n) {
    if (!isFinite(v)) return '—';
    const a = Math.abs(v);
    if (a !== 0 && (a >= 1e4 || a < 1e-3)) return v.toExponential(1);
    return (+v).toFixed(n == null ? 2 : n).replace(/\.?0+$/, '');
  }
  function text(parent, x, y, s, cls, anchor) {
    const t = add(parent, 'text', { x: x, y: y, class: cls || 'ph-ax', 'text-anchor': anchor || 'middle' });
    t.textContent = s;
    return t;
  }

  /* 从闭环特征多项式取主导二阶近似。 */
  function approximate(model, den) {
    den = den || model.cl_den || [];
    if (den.length < 3) return null;
    const rs = LC.roots(den);
    if (!rs.length) return null;
    const cx = rs.filter((z) => z.im > 1e-7).sort((a, b) => b.re - a.re);
    let s1, s2;
    if (cx.length) {
      s1 = cx[0];
      s2 = { re: s1.re, im: -s1.im };
    } else {
      const re = rs.slice().sort((a, b) => b.re - a.re);
      if (re.length < 2) return null;
      s1 = re[0]; s2 = re[1];
    }
    const snap = (v) => (Math.abs(v) < 1e-6 ? 0 : v);
    s1 = { re: snap(s1.re), im: snap(s1.im) };
    s2 = { re: snap(s2.re), im: snap(s2.im) };
    const a1 = -(s1.re + s2.re);
    const a2 = s1.re * s2.re - s1.im * s2.im;
    /* a2 = 0 表示有根在原点：此时没有二阶自治系统的相图（x'' + a1x' = 0 没有回复力），
       宁可不画，也不画一张错的。 */
    if (!isFinite(a1) || !isFinite(a2) || Math.abs(a2) < 1e-9) return null;
    /* 主导性检查：若还有根比这一对更靠右（衰减更慢，甚至落在右半平面），
       二阶近似就不再代表整体行为——只能当作该对根附近的局部相图。 */
    let blocker = null;
    const near = (z, w) => Math.hypot(z.re - w.re, z.im - w.im) < 1e-6;
    for (const z of rs) {
      if (near(z, s1) || near(z, s2)) continue;
      if (z.re > s1.re + 1e-6 && (!blocker || z.re > blocker.re)) blocker = z;
    }
    return { a1, a2, s1, s2, order: rs.length, osc: !!cx.length, approxOk: !blocker, blocker };
  }

  function classify(a1, a2) {
    const sig = -a1 / 2;
    const disc = a1 * a1 - 4 * a2;
    const complex = disc < -1e-9;
    /* 有根落在虚轴上：sig=0 的纯虚根（中心），或 a2=0 的原点根（积分型）。
       两者都是李雅普诺夫稳定但非渐近稳定，即临界稳定。 */
    const marginal = Math.abs(sig) < 1e-7 && a2 > -1e-9;
    let type, stable;
    if (a2 < -1e-9) { type = '鞍点'; stable = false; }
    else if (Math.abs(a2) < 1e-9) { type = '原点有根（退化）'; stable = false; }
    else if (complex) {
      if (marginal) { type = '中心'; stable = false; }
      else if (sig < 0) { type = '稳定焦点'; stable = true; }
      else { type = '不稳定焦点'; stable = false; }
    } else {
      if (marginal) { type = '临界结点'; stable = false; }
      else if (sig < 0) { type = '稳定结点'; stable = true; }
      else { type = '不稳定结点'; stable = false; }
    }
    return { type, stable, marginal, sig, complex, disc };
  }

  function flow(x, y) {
    /* 纵轴用 ẋ/ωn 归一化，使相图在 x/ẋ 两个方向上尺度可比。
       vy 里用 a2/wn 而不是 wn：a2<0（鞍点）时回复力反号，否则会把鞍点画成中心。 */
    const wn = S.wn || 1;
    return { vx: wn * y, vy: -(S.a2 / wn) * x - S.a1 * y };
  }

  function rk4(x, y, h) {
    const k1 = flow(x, y);
    const k2 = flow(x + .5 * h * k1.vx, y + .5 * h * k1.vy);
    const k3 = flow(x + .5 * h * k2.vx, y + .5 * h * k2.vy);
    const k4 = flow(x + h * k3.vx, y + h * k3.vy);
    return [x + h / 6 * (k1.vx + 2 * k2.vx + 2 * k3.vx + k4.vx),
            y + h / 6 * (k1.vy + 2 * k2.vy + 2 * k3.vy + k4.vy)];
  }

  function trajectory(x0, y0) {
    const out = [[x0, y0]];
    let x = x0, y = y0;
    const scale = Math.max(1, Math.abs(S.a1), S.wn);
    const h = Math.max(0.002, Math.min(0.04, 0.02 / scale));
    const n = 1600;
    for (let i = 0; i < n; i++) {
      const [nx, ny] = rk4(x, y, h);
      if (!isFinite(nx) || !isFinite(ny)) break;
      x = nx; y = ny;
      out.push([x, y]);
      if (Math.hypot(x, y) > S.R * 5) break;
    }
    return out;
  }

  function path(pts) {
    return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
  }

  function draw() {
    const svg = $('phaseSvg');
    if (!svg || !S.model) return;
    clear(svg);
    svg.setAttribute('viewBox', '0 0 ' + VB + ' ' + VB);
    const x0 = CX - HALF, x1 = CX + HALF, y0 = CY - HALF, y1 = CY + HALF;
    const R = S.R;
    const X = (v) => CX + v / R * HALF;
    const Y = (v) => CY - v / R * HALF;
    S.layout = { X, Y, R };

    const clipId = 'phaseClip';
    const defs = add(svg, 'defs', {});
    const cp = add(defs, 'clipPath', { id: clipId });
    add(cp, 'rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0 });

    /* 网格 */
    const ticks = [-R, -R / 2, 0, R / 2, R];
    for (const t of ticks) {
      add(svg, 'line', { x1: x0, y1: Y(t), x2: x1, y2: Y(t), class: 'ph-grid' });
      add(svg, 'line', { x1: X(t), y1: y0, x2: X(t), y2: y1, class: 'ph-grid' });
      if (t !== 0) {
        text(svg, X(t), y1 + 13, fmt(t, 1), 'ph-ax');
        text(svg, x0 - 6, Y(t) + 3, fmt(t, 1), 'ph-ax', 'end');
      }
    }
    add(svg, 'line', { x1: x0, y1: Y(0), x2: x1, y2: Y(0), class: 'ph-axis' });
    add(svg, 'line', { x1: X(0), y1: y0, x2: X(0), y2: y1, class: 'ph-axis' });
    text(svg, x1, Y(0) - 7, 'x₁', 'ph-axis', 'end');
    const yl = text(svg, 11, CY, 'ẋ/ωₙ', 'ph-axis', 'middle');
    yl.setAttribute('transform', 'rotate(-90 11 ' + CY + ')');

    const g = add(svg, 'g', { 'clip-path': 'url(#' + clipId + ')' });

    /* 矢量场 */
    const n = 12;
    for (let i = 0; i <= n; i++) {
      for (let j = 0; j <= n; j++) {
        const xv = -R + 2 * R * i / n, yv = -R + 2 * R * j / n;
        const v = flow(xv, yv);
        const norm = Math.hypot(v.vx, v.vy);
        if (!isFinite(norm) || norm < 1e-9) continue;
        const ux = v.vx / norm, uy = v.vy / norm;
        const len = 0.075 * (x1 - x0);
        const sx = X(xv), sy = Y(yv);
        const ex = sx + ux * len, ey = sy - uy * len;
        add(g, 'line', { x1: sx, y1: sy, x2: ex, y2: ey, class: 'ph-arrow' });
        const a = Math.atan2(-uy, ux), h = 3.4;
        const ax = Math.cos(a) / 2, ay = Math.sin(a) / 2;
        add(g, 'line', { x1: ex, y1: ey, x2: ex - h * (ax - ay), y2: ey - h * (ay + ax), class: 'ph-arrow' });
        add(g, 'line', { x1: ex, y1: ey, x2: ex - h * (ax + ay), y2: ey - h * (ay - ax), class: 'ph-arrow' });
      }
    }

    /* 默认轨迹 */
    const starts = [];
    if (S.type === '鞍点') {
      for (const s of [0.12, -0.12]) {
        starts.push([s * R, 0], [-s * R, 0], [0, s * R], [0, -s * R]);
      }
    } else {
      for (let k = 0; k < 8; k++) {
        const th = 2 * Math.PI * k / 8;
        starts.push([0.92 * R * Math.cos(th), 0.92 * R * Math.sin(th)]);
      }
    }
    for (const [sx, sy] of starts) {
      const pts = trajectory(sx, sy).map((p) => [X(p[0]), Y(p[1])]);
      if (pts.length > 2) add(g, 'path', { d: path(pts), class: 'ph-trail' });
    }
    for (const p of S.custom) {
      const pts = trajectory(p[0], p[1]).map((q) => [X(q[0]), Y(q[1])]);
      if (pts.length > 2) add(g, 'path', { d: path(pts), class: 'ph-trail ph-user' });
      add(g, 'circle', { cx: X(p[0]), cy: Y(p[1]), r: 2.6, class: 'ph-start' });
    }

    /* 平衡点 */
    add(g, 'circle', { cx: X(0), cy: Y(0), r: 4.2, class: 'ph-eq' });
    text(svg, X(0), Y(0) - 9, 'O', 'ph-ax', 'middle');
  }

  function info() {
    const el = $('phaseInfo');
    if (!el) return;
    const s1 = S.roots.s1, s2 = S.roots.s2;
    const eig = Math.abs(s1.im) > 1e-7
      ? fmt(s1.re, 2) + ' ± ' + fmt(Math.abs(s1.im), 2) + 'j'
      : fmt(s1.re, 2) + ' , ' + fmt(s2.re, 2);
    const badApprox = !S.fromOpen && S.approxOk === false;
    const b = S.blocker;
    const bStr = b ? fmt(b.re, 2) + (Math.abs(b.im) > 1e-7 ? '±' + fmt(Math.abs(b.im), 2) + 'j' : '') : '';
    const cls = badApprox ? 'ph-bad'
      : (S.marginal ? 'ph-warn' : (S.stable ? 'ph-good' : 'ph-bad'));
    const stabText = badApprox
      ? (b.re > 1e-9 ? '不稳定（另有极点 ' + bStr + '）' : '近似失效（另有慢极点 ' + bStr + '）')
      : (S.marginal ? '临界稳定' : (S.stable ? '稳定' : '不稳定'));
    const motion = S.type.indexOf('焦点') >= 0
      ? (S.stable ? '螺旋收敛到平衡点' : '螺旋发散，振幅增大')
      : S.type.indexOf('结点') >= 0
        ? (S.stable ? '沿两个方向收敛到平衡点' : '沿两个方向发散')
        : S.type === '鞍点'
          ? '沿稳定流形收敛、沿不稳定流形发散'
          : '等幅振荡，轨迹为闭曲线';
    el.innerHTML =
      '<div class="ph-type ' + cls + '">' + S.type + (badApprox ? '（局部）' : '') + '</div>' +
      '<div class="ph-kv"><span>特征根</span><b>' + eig + '</b></div>' +
      '<div class="ph-kv"><span>阻尼比</span><b>' + (S.a2 > 1e-9 ? fmt(Math.abs(S.a1) / (2 * Math.sqrt(Math.abs(S.a2))), 3) : '不适用') + '</b></div>' +
      '<div class="ph-kv"><span>自然频率</span><b>' + (S.a2 > 1e-9 ? fmt(S.wn, 3) + ' rad/s' : '不适用') + '</b></div>' +
      '<div class="ph-kv"><span>稳定性</span><b class="' + cls + '">' + stabText + '</b></div>' +
      '<div class="ph-kv"><span>邻域运动</span><b>' + motion + '</b></div>' +
      '<div class="ph-kv"><span>平衡点</span><b>(0, 0)</b></div>';
    const note = $('phaseNote');
    if (note) {
      let base;
      if (S.fromOpen) {
        base = S.olWanted
          ? '开环 G₀(s) 的相图：平衡点类型由开环极点决定（与预览增益无关）。'
          : '闭环特征式退化（极点落在原点，临界稳定），改画开环 G₀ 的相图：平衡点类型由开环极点决定。';
      } else if (S.olWanted) {
        base = '开环 G₀(s) 为 ' + S.order + ' 阶，不是二阶自治系统，此处仍画闭环相图。';
      } else if (S.order > 2) {
        base = '闭环 ' + S.order + ' 阶，取' + (S.osc ? '主导振荡极点对' : '两个主导实极点') + '作二阶近似；其余极点更快。';
      } else {
        base = '闭环二阶系统，相图与特征根一一对应。';
      }
      note.textContent = base
        + (badApprox
          ? ' 注意：闭环另有极点 ' + bStr + ' 比这一对更靠右，二阶近似只描述该对根附近的局部行为，整体稳定性以稳定性卡为准。'
          : '')
        + (S.gain !== 1 && !S.fromOpen ? ' · 预览增益 ×' + S.gain.toFixed(2) : '');
    }
  }

  function rebuild() {
    if (!S.model) return;
    const num = S.baseNum ? LC.polyscale(S.baseNum, S.gain) : null;
    const den = S.baseDen ? LC.polyadd(S.baseDen, num) : (S.model.cl_den || []);
    const wantOl = S.sys === 'ol';
    const olOk = !!(S.baseDen && S.baseDen.length === 3 && Math.abs(S.baseDen[0]) > 1e-12);
    const openAp = () => {
      if (!olOk) return null;
      const c = S.baseDen[0];
      return approximate(S.model, S.baseDen.map((v) => v / c));
    };
    /* 选「开环 G₀」时优先画开环分母的相图（与预览增益无关）。 */
    let ap = wantOl ? openAp() : null;
    let fromOpen = !!ap;
    if (!ap) { ap = approximate(S.model, den); fromOpen = false; }
    /* 闭环特征式退化（原点有根，二阶近似不存在）时，退回画开环 G₀ 的相图：
       例如 G₀=1/(s²-1) 闭环 Φ=s²/(s²-1) → 特征式 s²，开环极点 ±1 才对应经典鞍点。 */
    if (!ap) { ap = openAp(); fromOpen = !!ap; }
    const card = $('phaseCard');
    const tag = $('phaseTag');
    if (!ap) {
      if (card) card.hidden = true;
      return;
    }
    if (card) card.hidden = false;
    S.fromOpen = fromOpen;
    S.olWanted = wantOl;
    if (tag) {
      tag.textContent = fromOpen
        ? (wantOl ? '开环 G₀' : '开环二阶（闭环退化）')
        : (ap.order > 2 ? '主导二阶' : '闭环二阶');
    }
    S.roots = ap; S.a1 = ap.a1; S.a2 = ap.a2; S.order = ap.order; S.osc = ap.osc;
    S.approxOk = ap.approxOk !== false; S.blocker = ap.blocker || null;
    S.wn = Math.sqrt(Math.abs(ap.a2)) || 1;
    const cls = classify(ap.a1, ap.a2);
    S.type = cls.type; S.stable = cls.stable; S.marginal = cls.marginal;
    S.custom = [];
    const slider = $('phaseR'), lab = $('phaseRv');
    if (slider) slider.value = String(S.R);
    if (lab) lab.textContent = '±' + S.R.toFixed(1);
    draw(); info();
  }

  function update(model) {
    const card = $('phaseCard');
    if (!card) return;
    if (!model || !model.cl_den || model.cl_den.length < 3) {
      card.hidden = true; S.model = null; return;
    }
    S.model = model;
    S.baseNum = model.ol_num ? model.ol_num.slice() : null;
    S.baseDen = model.ol_den ? model.ol_den.slice() : null;
    S.gain = 1;
    rebuild();
  }

  function setGain(k) {
    S.gain = Math.max(0.05, +k || 1);
    if (S.raf) return;
    S.raf = requestAnimationFrame(() => { S.raf = 0; rebuild(); });
  }

  function bind() {
    const svg = $('phaseSvg');
    if (svg) {
      svg.addEventListener('click', (e) => {
        if (!S.layout) return;
        const r = svg.getBoundingClientRect();
        const vx = (e.clientX - r.left) / r.width * VB;
        const vy = (e.clientY - r.top) / r.height * VB;
        const x = (vx - CX) / HALF * S.R;
        const y = (CY - vy) / HALF * S.R;
        if (Math.abs(x) > S.R || Math.abs(y) > S.R) return;
        if (Math.abs(x) < 1e-3 && Math.abs(y) < 1e-3) return;
        S.custom.push([x, y]);
        if (S.custom.length > 12) S.custom.shift();
        draw();
      });
    }
    const slider = $('phaseR'), lab = $('phaseRv');
    if (slider) {
      slider.addEventListener('input', () => {
        S.R = Math.max(0.5, +slider.value || 2.5);
        if (lab) lab.textContent = '±' + S.R.toFixed(1);
        S.custom = [];
        draw();
      });
    }
    const reset = $('phaseReset');
    if (reset) reset.addEventListener('click', () => { S.custom = []; draw(); });
    const sysSel = $('phaseSys');
    if (sysSel) {
      const q = new URLSearchParams(location.search).get('psys');
      if (q === 'ol' || q === 'cl') S.sys = q;
      sysSel.value = S.sys;
      sysSel.addEventListener('change', () => {
        S.sys = sysSel.value === 'ol' ? 'ol' : 'cl';
        S.custom = [];
        rebuild();
      });
    }
    const liveK = $('liveK');
    if (liveK) liveK.addEventListener('input', () => setGain(+liveK.value || 1));
  }

  window.PhaseWorkbench = { update, setGain };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
