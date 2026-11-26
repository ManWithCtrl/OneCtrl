/* Interactive Nyquist view: pan by dragging, wheel/pinch to zoom. */
(function () {
  'use strict';
  var LC = window.LiveCore;
  if (!LC) return;

  var NS = 'http://www.w3.org/2000/svg';
  var VB = 360, PAD = 30, PLOT = VB - 2 * PAD, C = VB / 2;
  var S = {
    model: null, pts: [], fit: null, K: 1, dfKind: null, M: 1, a: 1,
    cx: 0, cy: 0, R: 5, hasInt: false, arc: 0
  };
  var drag = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function fmt(v, n) {
    if (!isFinite(v)) return '—';
    var a = Math.abs(v);
    if (a !== 0 && (a < 1e-3 || a >= 1e4)) return v.toExponential(1);
    var s = v.toFixed(n == null ? 3 : n);
    return s.replace(/\.?0+$/, '');
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function mapX(x) { return PAD + (x - (S.cx - S.R)) / (2 * S.R) * PLOT; }
  function mapY(y) { return PAD + ((S.cy + S.R) - y) / (2 * S.R) * PLOT; }

  function tri(svg, x, y, ang, cls) {
    var L = 9, W = 5.2;
    var dx = Math.cos(ang) * L, dy = Math.sin(ang) * L;
    var px = -Math.sin(ang) * W, py = Math.cos(ang) * W;
    var d = 'M' + x + ',' + y +
      'L' + (x + dx + px) + ',' + (y + dy + py) +
      'L' + (x + dx - px) + ',' + (y + dy - py) + 'z';
    el('path', { d: d, class: cls }, svg);
  }

  function tfAt(w) {
    var s = { re: 0, im: w };
    var n = LC.polyval(LC.polyscale(S.model.ol_num, S.K), s);
    var d = LC.polyval(S.model.ol_den, s);
    return LC.cdiv(n, d);
  }

  function niceStep(span) {
    var raw = span / 6, p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var n = raw / p;
    var k = n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10;
    return k * p;
  }

  // −1/N(A)：滞环继电器是复值（Im = −πa/(4M) 的水平射线），其余落在实轴上
  function negInvC(A) {
    var M = S.M, a = S.a;
    if (!(A > 0)) return null;
    if (S.dfKind === 'relay') return { re: -Math.PI * A / (4 * M), im: 0 };
    if (S.dfKind === 'relay_dz') {
      if (A <= a) return null;
      var q = Math.sqrt(Math.max(0, 1 - (a / A) * (a / A)));
      return q > 1e-9 ? { re: -Math.PI * A / (4 * M * q), im: 0 } : null;
    }
    if (S.dfKind === 'relay_hyst') {
      if (A <= a) return null;
      var h = Math.PI * a / (4 * M);
      return { re: -Math.PI * Math.sqrt(A * A - a * a) / (4 * M), im: -h };
    }
    if (S.dfKind === 'sat') {
      var r = Math.min(1, a / A);
      var N = (2 / Math.PI) * (Math.asin(r) + r * Math.sqrt(Math.max(0, 1 - r * r)));
      return N > 1e-9 ? { re: -1 / N, im: 0 } : null;
    }
    return null;
  }
  function negInv(A) {
    var v = negInvC(A);
    return v ? v.re : NaN;
  }
  function dfLevel() {
    return S.dfKind === 'relay_hyst' ? -Math.PI * S.a / (4 * S.M) : 0;
  }
  function solveAmps(x) {
    var out = [], i, A, lo, hi, fl, fh, mid, fm;
    if (S.dfKind === 'relay') {
      A = -4 * S.M * x / Math.PI;
      if (isFinite(A) && A > 0) out.push(A);
      return out;
    }
    if (S.dfKind === 'relay_hyst') {
      A = Math.sqrt(S.a * S.a + Math.pow(4 * S.M * Math.abs(x) / Math.PI, 2));
      if (isFinite(A) && A > 0) out.push(A);
      return out;
    }
    var start = S.dfKind === 'relay_dz' ? S.a * 1.0001 : 1e-3;
    var end = 30;
    var lastA = start, lastF = negInv(lastA) - x;
    for (i = 1; i <= 600; i++) {
      A = start * Math.pow(end / start, i / 600);
      var f = negInv(A) - x;
      if (!isFinite(f)) { lastA = A; lastF = f; continue; }
      if (isFinite(lastF) && lastF * f <= 0) {
        lo = lastA; hi = A; fl = lastF;
        for (var j = 0; j < 50; j++) {
          mid = (lo + hi) / 2; fm = negInv(mid) - x;
          if (fl * fm <= 0) { hi = mid; } else { lo = mid; fl = fm; }
        }
        var root = (lo + hi) / 2;
        if (!out.some(function (v) { return Math.abs(v - root) < 1e-4; })) out.push(root);
      }
      lastA = A; lastF = f;
    }
    return out;
  }
  function crossings() {
    var out = [], p = S.pts, lv = dfLevel();
    for (var i = 1; i < p.length; i++) {
      var a = p[i - 1], b = p[i];
      if (!isFinite(a.im) || !isFinite(b.im)) continue;
      var d0 = a.im - lv, d1 = b.im - lv;
      if (d0 === 0 || d0 * d1 < 0) {
        var t = Math.abs(d0) / (Math.abs(d0) + Math.abs(d1) || 1);
        var x = a.re + (b.re - a.re) * t;
        var w = a.w + (b.w - a.w) * t;
        if (x < 0) out.push({ x: x, w: w, level: lv });
      }
    }
    return out;
  }

  function fit() {
    var pts = S.pts;
    // 只围绕 (-1,0) 附近取景；DC 增益很大的曲线远端不应把 -1 压成一点。
    var cap = 6.0;
    var minX = -1, maxX = 0, maxIm = 0;
    for (var j = 0; j < pts.length; j++) {
      var p = pts[j];
      if (!isFinite(p.re) || !isFinite(p.im)) continue;
      if (Math.abs(p.re) > cap || Math.abs(p.im) > cap) continue;
      minX = Math.min(minX, p.re); maxX = Math.max(maxX, p.re);
      maxIm = Math.max(maxIm, Math.abs(p.im));
    }
    if (S.dfKind) {
      maxIm = Math.max(maxIm, Math.abs(dfLevel()));
      crossings().forEach(function (c) {
        minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
      });
    }
    var cx = (minX + maxX) / 2, cy = 0;
    var R = Math.max((maxX - minX) / 2, maxIm) * 1.15;
    if (S.hasInt) {
      cx = 0;
      R = Math.max(R, Math.abs(minX), Math.abs(maxX), maxIm) * 1.18;
    }
    if (!isFinite(R) || R < 0.4) R = 0.4;
    S.fit = { cx: cx, cy: cy, R: R };
    S.cx = cx; S.cy = cy; S.R = R;
  }

  function build(model) {
    S.model = model;
    S.dfKind = model.nl && model.nl !== 'none' ? model.nl : null;
    S.M = model.M == null ? 1 : +model.M;
    S.a = model.a == null ? 1 : +model.a;
    var den = model.ol_den || [];
    var wc = model.wc || 1;
    var wmin = Math.max(1e-6, wc / 2500), wmax = Math.max(wc * 2500, 1000);
    var N = 720, pts = [];
    for (var i = 0; i < N; i++) {
      var w = wmin * Math.pow(wmax / wmin, i / (N - 1));
      var z = tfAt(w);
      if (z && isFinite(z.re) && isFinite(z.im)) pts.push({ re: z.re, im: z.im, w: w });
    }
    S.pts = pts;
    var mx = 1;
    for (var k = 0; k < den.length; k++) mx = Math.max(mx, Math.abs(den[k]));
    S.hasInt = den.length > 1 && Math.abs(den[den.length - 1]) < 1e-12 * mx;
    fit();
  }

  // 曲线在 ω→0 时可能远超画布（双积分器 G(jω) 发散，坐标能到 ±1e8 px）。
  // 超出画布 LIMIT 像素就用 Liang–Barsky 截断在边界上并断开路径，避免超长坐标拖慢渲染。
  var LIMIT = 260;
  function inBox(x, y) {
    return x > PAD - LIMIT && x < PAD + PLOT + LIMIT &&
           y > PAD - LIMIT && y < PAD + PLOT + LIMIT;
  }
  function clipSeg(ax, ay, bx, by) {
    var x0 = PAD - LIMIT, x1 = PAD + PLOT + LIMIT;
    var y0 = PAD - LIMIT, y1 = PAD + PLOT + LIMIT;
    var dx = bx - ax, dy = by - ay, t0 = 0, t1 = 1;
    var p = [-dx, dx, -dy, dy], q = [ax - x0, x1 - ax, ay - y0, y1 - ay];
    for (var i = 0; i < 4; i++) {
      if (Math.abs(p[i]) < 1e-12) {
        if (q[i] < 0) return null;
        continue;
      }
      var r = q[i] / p[i];
      if (p[i] < 0) { if (r > t1) return null; if (r > t0) t0 = r; }
      else { if (r < t0) return null; if (r < t1) t1 = r; }
    }
    return { x: ax + t0 * dx, y: ay + t0 * dy, cut: t1 < 1 };
  }
  function pathFor(sign) {
    var d = '', started = false, px = 0, py = 0;
    for (var i = 0; i < S.pts.length; i++) {
      var p = S.pts[i];
      var x = mapX(p.re), y = mapY(sign * p.im);
      if (!isFinite(x) || !isFinite(y)) continue;
      if (!started) {
        if (!inBox(x, y)) continue;
        d += 'M' + x.toFixed(1) + ' ' + y.toFixed(1);
        started = true; px = x; py = y;
        continue;
      }
      var seg = clipSeg(px, py, x, y);
      if (!seg) { started = false; continue; }
      d += 'L' + seg.x.toFixed(1) + ' ' + seg.y.toFixed(1);
      if (seg.cut) { started = false; } else { px = x; py = y; }
    }
    return d;
  }

  function draw() {
    var svg = $('nyqSvg');
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    el('rect', { x: 0, y: 0, width: VB, height: VB, rx: 8, class: 'nyq-bg' }, svg);
    var defs = el('defs', null, svg);
    var cp = el('clipPath', { id: 'nyqClip' }, defs);
    el('rect', { x: PAD, y: PAD, width: PLOT, height: PLOT }, cp);

    var step = niceStep(2 * S.R);
    var x0 = Math.ceil((S.cx - S.R) / step) * step;
    var y0 = Math.ceil((S.cy - S.R) / step) * step;
    var x, y;
    for (x = x0; x <= S.cx + S.R + 1e-9; x += step) {
      var sx = mapX(x);
      el('line', { x1: sx, x2: sx, y1: PAD, y2: PAD + PLOT, class: 'nyq-grid' }, svg);
      if (Math.abs(x) > 1e-12) {
        var tx = el('text', { x: sx, y: PAD + PLOT + 14, 'text-anchor': 'middle', class: 'nyq-tick' }, svg);
        tx.textContent = fmt(x, 2);
      }
    }
    for (y = y0; y <= S.cy + S.R + 1e-9; y += step) {
      var sy = mapY(y);
      el('line', { x1: PAD, x2: PAD + PLOT, y1: sy, y2: sy, class: 'nyq-grid' }, svg);
      if (Math.abs(y) > 1e-12) {
        var ty = el('text', { x: PAD - 6, y: sy + 3, 'text-anchor': 'end', class: 'nyq-tick' }, svg);
        ty.textContent = fmt(y, 2);
      }
    }
    var ax = mapX(0), ay = mapY(0);
    if (ax >= PAD && ax <= PAD + PLOT) el('line', { x1: ax, x2: ax, y1: PAD, y2: PAD + PLOT, class: 'nyq-axis' }, svg);
    if (ay >= PAD && ay <= PAD + PLOT) el('line', { x1: PAD, x2: PAD + PLOT, y1: ay, y2: ay, class: 'nyq-axis' }, svg);
    el('text', { x: PAD + PLOT, y: ay - 6, 'text-anchor': 'end', class: 'nyq-label' }, svg).textContent = 'Re';
    el('text', { x: ax + 6, y: PAD - 8, 'text-anchor': 'start', class: 'nyq-label' }, svg).textContent = 'Im';

    var pd = pathFor(1);
    if (pd) el('path', { d: pd, class: 'nyq-curve', 'clip-path': 'url(#nyqClip)',
      'marker-end': 'url(#nyqArrow)' }, svg);
    if (S.pts.length > 8) {
      [0.92].forEach(function (fr) {
        var i = Math.max(1, Math.min(S.pts.length - 2, Math.round(fr * (S.pts.length - 1))));
        var p0 = S.pts[i - 1], p1 = S.pts[i], p2 = S.pts[i + 1];
        if (!p0 || !p1 || !p2) return;
        var x = mapX(p1.re), y = mapY(p1.im);
        if (!inBox(x, y)) return;
        var ang = Math.atan2(mapY(p0.im) - mapY(p2.im), mapX(p0.re) - mapX(p2.re));
        tri(svg, x, y, ang, 'nyq-dir');
      });
    }
    var md = pathFor(-1);
    if (md) el('path', { d: md, class: 'nyq-mirror', 'clip-path': 'url(#nyqClip)' }, svg);

    if (S.dfKind) {
      var dd = '', started = false, A, v, dpx = 0, dpy = 0;
      for (var ia = 0; ia <= 240; ia++) {
        A = 0.02 * Math.pow(500000, ia / 240);
        v = negInvC(A);
        if (!v) continue;
        var sx = mapX(v.re), sy2 = mapY(v.im);
        if (!isFinite(sx) || !isFinite(sy2)) continue;
        if (!started) {
          if (!inBox(sx, sy2)) continue;
          dd += 'M' + sx.toFixed(1) + ' ' + sy2.toFixed(1);
          started = true; dpx = sx; dpy = sy2;
          continue;
        }
        var dseg = clipSeg(dpx, dpy, sx, sy2);
        if (!dseg) { started = false; continue; }
        dd += 'L' + dseg.x.toFixed(1) + ' ' + dseg.y.toFixed(1);
        if (dseg.cut) { started = false; } else { dpx = sx; dpy = sy2; }
      }
      if (dd) el('path', { d: dd, class: 'nyq-df', 'clip-path': 'url(#nyqClip)' }, svg);
      S.dfCycles = [];
      var cr = crossings();
      for (var ci = 0; ci < cr.length; ci++) {
        var amps = solveAmps(cr[ci].x);
        for (var ai = 0; ai < amps.length; ai++) {
          S.dfCycles.push({ A: amps[ai], w: cr[ci].w, T: 2 * Math.PI / cr[ci].w });
          el('circle', { cx: mapX(cr[ci].x), cy: mapY(cr[ci].level), r: 6, class: 'nyq-cycle' }, svg);
        }
      }
    } else {
      S.dfCycles = [];
    }

    if (S.hasInt) {
      var Rarc = S.R * 0.90, pr = Rarc / (2 * S.R) * PLOT;
      var a0 = { x: mapX(0), y: mapY(-Rarc) }, a1 = { x: mapX(0), y: mapY(Rarc) };
      el('path', { d: 'M' + a0.x + ' ' + a0.y + 'A' + pr + ' ' + pr + ' 0 0 0 ' + a1.x + ' ' + a1.y,
        class: 'nyq-arc' }, svg);
      var ath = Math.PI / 3;
      tri(svg, mapX(Rarc * Math.cos(ath)), mapY(Rarc * Math.sin(ath)), Math.atan2(Math.cos(ath), Math.sin(ath)), 'nyq-arc-dir');
      var at = el('text', { x: mapX(Rarc * 0.45), y: mapY(-Rarc * 0.60),
        'text-anchor': 'middle', class: 'nyq-arc-label' }, svg);
      at.textContent = '积分补线（∞）';
      var lb0 = el('text', { x: mapX(0) + 6, y: mapY(-Rarc) + 14,
        class: 'nyq-arc-end' }, svg); lb0.textContent = '0⁺';
      var lb1 = el('text', { x: mapX(0) + 6, y: mapY(Rarc) - 6,
        class: 'nyq-arc-end' }, svg); lb1.textContent = '0⁻';
    }

    var m = el('g', { class: 'nyq-minus', transform: 'translate(' + mapX(-1) + ' ' + mapY(0) + ')' }, svg);
    el('circle', { r: 5.2, class: 'nyq-minus-dot' }, m);
    var ml = el('text', { x: 8, y: -8, class: 'nyq-minus-label' }, m);
    ml.textContent = '(−1,j0)';

    var cl = S.model && S.model.poles_cl || [];
    for (var q = 0; q < cl.length; q++) {
      var p = cl[q];
      if (!p || Math.abs(p[1]) > 1e-7) continue;
      el('circle', { cx: mapX(p[0]), cy: mapY(p[1]), r: 3, class: 'nyq-pole' }, svg);
    }

    var read = $('nyqRead');
    if (read) {
      var msg = '拖动平移 · 滚轮/二指缩放 · K=' + fmt(S.K, 2) + ' · 视野约 ±' + fmt(S.R, 3);
      if (S.dfKind) {
        var cyc = S.dfCycles || [];
        msg += cyc.length ? ' · 自振点 ' + cyc.map(function (c) {
          return 'A=' + fmt(c.A, 3) + ',ω=' + fmt(c.w, 3) + ',T=' + fmt(c.T, 2) + 's';
        }).join('；') : ' · 无自振点';
      }
      read.textContent = msg;
    }
  }

  var ptrs = new Map();
  var pinch = null;

  function onDown(e) {
    if (e.button != null && e.button !== 0) return;
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
    if (ptrs.size === 1) {
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, cx: S.cx, cy: S.cy };
    } else if (ptrs.size === 2) {
      var r = e.currentTarget.getBoundingClientRect();
      var arr = Array.from(ptrs.values());
      var mx = (arr[0].x + arr[1].x) / 2, my = (arr[0].y + arr[1].y) / 2;
      pinch = { d: Math.hypot(arr[0].x - arr[1].x, arr[0].y - arr[1].y) || 1,
                px: (mx - r.left) / r.width, py: (my - r.top) / r.height,
                cx: S.cx, cy: S.cy, R: S.R };
      drag = null;
    }
    e.currentTarget.classList.add('dragging');
    e.preventDefault();
  }
  function onMove(e) {
    if (!ptrs.has(e.pointerId)) return;
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    var r = e.currentTarget.getBoundingClientRect();
    if (!r.width || !r.height) return;
    if (ptrs.size >= 2 && pinch) {
      var arr = Array.from(ptrs.values());
      var mx = (arr[0].x + arr[1].x) / 2, my = (arr[0].y + arr[1].y) / 2;
      var px = (mx - r.left) / r.width, py = (my - r.top) / r.height;
      var lo = S.fit ? S.fit.R / 10 : 0.05, hi = S.fit ? S.fit.R * 10 : 500;
      var nR = clamp(pinch.R * pinch.d / (Math.hypot(arr[0].x - arr[1].x, arr[0].y - arr[1].y) || 1), lo, hi);
      var x = pinch.cx + (2 * pinch.px - 1) * pinch.R;
      var y = pinch.cy + (1 - 2 * pinch.py) * pinch.R;
      S.R = nR;
      S.cx = x - (2 * px - 1) * nR;
      S.cy = y - (1 - 2 * py) * nR;
      draw();
    } else if (drag && drag.id === e.pointerId) {
      var dx = (e.clientX - drag.x) / r.width * 2 * S.R;
      var dy = (e.clientY - drag.y) / r.height * 2 * S.R;
      S.cx = drag.cx - dx;
      S.cy = drag.cy + dy;
      draw();
    }
    e.preventDefault();
  }
  function onUp(e) {
    ptrs.delete(e.pointerId);
    if (ptrs.size < 2) pinch = null;
    if (ptrs.size === 1) {
      var id = Array.from(ptrs.keys())[0], p = ptrs.get(id);
      drag = { id: id, x: p.x, y: p.y, cx: S.cx, cy: S.cy };
    } else if (!ptrs.size) {
      drag = null;
      e.currentTarget.classList.remove('dragging');
    }
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch (_) {}
  }
  function onWheel(e) {
    e.preventDefault();
    var f = Math.exp(e.deltaY * 0.0015);
    var r = e.currentTarget.getBoundingClientRect();
    if (!r.width || !r.height) return;
    var px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
    var x = S.cx + (2 * px - 1) * S.R;
    var y = S.cy + (1 - 2 * py) * S.R;
    var lo = S.fit ? S.fit.R / 10 : 0.05, hi = S.fit ? S.fit.R * 10 : 500;
    var nR = clamp(S.R * f, lo, hi);
    S.cx = x - (2 * px - 1) * nR;
    S.cy = y - (1 - 2 * py) * nR;
    S.R = nR;
    draw();
  }

  function bind() {
    var svg = $('nyqSvg');
    if (!svg || svg.dataset.bound) return;
    svg.dataset.bound = '1';
    svg.addEventListener('pointerdown', onDown);
    svg.addEventListener('pointermove', onMove);
    svg.addEventListener('pointerup', onUp);
    svg.addEventListener('pointercancel', onUp);
    svg.addEventListener('wheel', onWheel, { passive: false });
    var kslider = $('nyqK'), klab = $('nyqKv');
    if (kslider) {
      kslider.value = '500';
      if (klab) klab.textContent = 'K=1.00';
      kslider.addEventListener('input', function () {
        var t = (+kslider.value || 0) / 1000;
        S.K = Math.pow(10, -2 + 4 * t);
        if (klab) klab.textContent = 'K=' + S.K.toFixed(2);
        if (S.model) { build(S.model); draw(); }
      });
    }
    var reset = $('nyqReset');
    if (reset) reset.addEventListener('click', function () {
      if (S.fit) { S.cx = S.fit.cx; S.cy = S.fit.cy; S.R = S.fit.R; draw(); }
    });
  }

  function update(model) {
    var card = $('nyqCard');
    if (!card) return;
    bind();
    if (!model || !model.ol_den || model.ol_den.length < 2) {
      card.hidden = true;
      return;
    }
    build(model);
    card.hidden = false;
    draw();
  }

  window.NyquistWorkbench = { update: update, state: function () { return { pts: S.pts, fit: S.fit, R: S.R, cx: S.cx, cy: S.cy }; } };
})();
