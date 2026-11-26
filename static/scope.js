/* 示波器 · 阶跃响应三通道（浏览器端 Canvas 2D） */
(function () {
  'use strict';
  if (!window.LiveCore) return;
  var LC = window.LiveCore;

  var CARD = null, CV = null, CTX = null;
  var W = 0, H = 0, DPR = 1;
  var raf = 0, lastW = 0;
  var S = {
    model: null, gain: 1, span: 1, tMax: 1,
    t: [], r: [], c: [], e: [], n: 0,
    met: null, progress: 1, paused: false, cursor: null,
    showR: true, showC: true, showE: true
  };

  var COL = {
    r: '#ffcf5a', c: '#4fd7ff', e: '#ff7ad9',
    bg: '#060a0f', grid: 'rgba(120,180,220,0.10)',
    border: 'rgba(120,180,220,0.28)', text: '#7f97a8',
    axis: '#9db3c1'
  };
  var PAD = { l: 46, r: 14, t: 18, b: 28 };

  function $(id) { return document.getElementById(id); }

  function num(v, d) {
    if (!isFinite(v)) return '—';
    var a = Math.abs(v);
    if (a >= 100) return v.toFixed(0);
    if (a >= 10) return v.toFixed(1);
    return v.toFixed(d == null ? 3 : d);
  }

  function size() {
    var shell = $('scopeShell');
    if (!shell || CARD.hidden) return false;
    var raw = shell.clientWidth;
    if (raw < 200) return false;
    var w = Math.max(280, raw - 12);
    if (w === lastW && CTX) return true;
    lastW = w;
    W = w;
    H = window.innerWidth <= 700 ? 240 : Math.min(380, Math.max(260, Math.round(W * 0.42)));
    DPR = window.devicePixelRatio || 1;
    CV.width = Math.round(W * DPR);
    CV.height = Math.round(H * DPR);
    CV.style.width = W + 'px';
    CV.style.height = H + 'px';
    CTX = CV.getContext('2d');
    CTX.setTransform(DPR, 0, 0, DPR, 0, 0);
    return true;
  }

  function plotBox() {
    return { l: PAD.l, r: W - PAD.r, t: PAD.t, b: H - PAD.b, w: W - PAD.l - PAD.r, h: H - PAD.t - PAD.b };
  }

  function yRange(end) {
    var lo = 0, hi = 0;
    for (var i = 0; i < end; i++) {
      if (S.showR) { if (S.r[i] < lo) lo = S.r[i]; if (S.r[i] > hi) hi = S.r[i]; }
      if (S.showC) { if (S.c[i] < lo) lo = S.c[i]; if (S.c[i] > hi) hi = S.c[i]; }
      if (S.showE) { if (S.e[i] < lo) lo = S.e[i]; if (S.e[i] > hi) hi = S.e[i]; }
    }
    if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
    if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
    var pad = (hi - lo) * 0.12;
    lo -= pad; hi += pad;
    if (lo > 0) lo = 0;
    if (hi < 0) hi = 0;
    return { lo: lo, hi: hi };
  }

  function draw() {
    if (!CTX || !S.model) return;
    var box = plotBox();
    var nShow = S.n ? Math.max(2, Math.round(S.n * S.progress)) : 0;
    var yr = yRange(S.n);
    var X = function (t) { return box.l + (t / Math.max(S.tMax, 1e-6)) * box.w; };
    var Y = function (v) { return box.b - ((v - yr.lo) / (yr.hi - yr.lo)) * box.h; };

    CTX.clearRect(0, 0, W, H);
    CTX.fillStyle = COL.bg;
    CTX.fillRect(0, 0, W, H);

    /* 网格 10×8 */
    CTX.lineWidth = 1;
    CTX.strokeStyle = COL.grid;
    for (var i = 0; i <= 10; i++) {
      var x = box.l + box.w * i / 10;
      CTX.beginPath(); CTX.moveTo(x, box.t); CTX.lineTo(x, box.b); CTX.stroke();
    }
    for (var j = 0; j <= 8; j++) {
      var y = box.t + box.h * j / 8;
      CTX.beginPath(); CTX.moveTo(box.l, y); CTX.lineTo(box.r, y); CTX.stroke();
    }

    /* 外框 */
    CTX.strokeStyle = COL.border;
    CTX.strokeRect(box.l, box.t, box.w, box.h);

    /* 零线 */
    if (yr.lo < 0 && yr.hi > 0) {
      CTX.strokeStyle = 'rgba(150,180,200,0.32)';
      CTX.beginPath(); CTX.moveTo(box.l, Y(0)); CTX.lineTo(box.r, Y(0)); CTX.stroke();
    }

    /* 坐标标签 */
    CTX.fillStyle = COL.text;
    CTX.font = '10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    CTX.textAlign = 'right';
    CTX.textBaseline = 'middle';
    for (var k = 0; k <= 4; k++) {
      var yv = yr.lo + (yr.hi - yr.lo) * k / 4;
      CTX.fillText(num(yv, 2), box.l - 6, Y(yv));
    }
    CTX.textAlign = 'center';
    CTX.textBaseline = 'top';
    for (var m = 0; m <= 4; m++) {
      var tv = S.tMax * m / 4;
      CTX.fillText(num(tv, tv < 1 ? 2 : 1), X(tv), box.b + 6);
    }
    CTX.fillStyle = COL.axis;
    CTX.font = '10px "Microsoft YaHei", "PingFang SC", sans-serif';
    CTX.textAlign = 'center';
    CTX.fillText('t (s)', box.l + box.w / 2, box.b + 16);
    CTX.textAlign = 'right';
    CTX.textBaseline = 'top';
    CTX.fillText('幅值', box.r, 4);

    if (!nShow) return;

    /* 通道曲线 */
    function trace(arr, color) {
      CTX.strokeStyle = color;
      CTX.lineWidth = 1.7;
      CTX.lineJoin = 'round';
      CTX.beginPath();
      for (var q = 0; q < nShow; q++) {
        var xx = X(S.t[q]), yy = Y(arr[q]);
        if (q === 0) CTX.moveTo(xx, yy); else CTX.lineTo(xx, yy);
      }
      CTX.stroke();
    }
    if (S.showR) trace(S.r, COL.r);
    if (S.showC) trace(S.c, COL.c);
    if (S.showE) trace(S.e, COL.e);

    /* 扫描线 */
    if (S.progress < 1) {
      var sx = X(S.t[nShow - 1]);
      CTX.strokeStyle = 'rgba(160,220,255,0.22)';
      CTX.beginPath(); CTX.moveTo(sx, box.t); CTX.lineTo(sx, box.b); CTX.stroke();
    }

    /* 游标 */
    if (S.cursor != null) {
      var idx = Math.min(S.cursor, nShow - 1);
      if (idx >= 0) {
        var cx = X(S.t[idx]);
        CTX.strokeStyle = 'rgba(220,235,245,0.42)';
        CTX.setLineDash([3, 3]);
        CTX.beginPath(); CTX.moveTo(cx, box.t); CTX.lineTo(cx, box.b); CTX.stroke();
        CTX.setLineDash([]);
        var dots = [
          [S.showR, S.r, COL.r], [S.showC, S.c, COL.c], [S.showE, S.e, COL.e]
        ];
        for (var d = 0; d < dots.length; d++) {
          if (!dots[d][0]) continue;
          CTX.fillStyle = dots[d][2];
          CTX.beginPath(); CTX.arc(cx, Y(dots[d][1][idx]), 2.6, 0, Math.PI * 2); CTX.fill();
        }
      }
    }
  }

  function nearestIndex(t) {
    var lo = 0, hi = S.n - 1;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (S.t[mid] < t) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(S.t[lo - 1] - t) < Math.abs(S.t[lo] - t)) lo--;
    return lo;
  }

  function updateRead() {
    var met = S.met;
    var m = $('scopeMetrics');
    if (m && met) {
      if (S.marginal) {
        m.textContent = '⚠ 闭环临界稳定：σ / tp / ts / y∞ 不定义（轨迹为斜坡或等幅振荡）';
      } else {
        m.textContent = 'σ ' + num(met.sigma, 2) + '% · tp ' + num(met.tp * 1000, 1) +
          ' ms · ts ' + num(met.ts * 1000, 1) + ' ms · y∞ ' + num(met.ss, 3);
      }
    }
    var c = $('scopeCursor');
    if (!c) return;
    if (S.cursor == null || !S.n) { c.textContent = '移动指针查看读数'; return; }
    var i = Math.min(S.cursor, S.n - 1);
    c.textContent = 't ' + num(S.t[i], 3) + ' s   r ' + num(S.r[i], 3) +
      '   c ' + num(S.c[i], 3) + '   e ' + num(S.e[i], 3);
  }

  function rebuild() {
    var m = S.model;
    if (!m || !m.ol_num || !m.ol_den) return false;
    var den = LC.polyadd(m.ol_den, LC.polyscale(m.ol_num, S.gain));
    var sr = LC.stepResponse(m.ol_num, den, 1600, S.span);
    var tMax = Math.min(S.span, sr.tEnd || S.span);
    if (!isFinite(tMax) || tMax <= 0) tMax = sr.tEnd || S.span;
    var n = 0;
    for (var i = 0; i < sr.t.length; i++) { if (sr.t[i] <= tMax + 1e-9) n++; else break; }
    if (n < 2) { n = Math.min(sr.t.length, 2); tMax = sr.t[1] || 0.1; }
    S.tMax = Math.max(0.01, tMax);
    S.n = n;
    S.t = sr.t.slice(0, n);
    S.c = sr.y.slice(0, n);
    S.r = new Array(n);
    S.e = new Array(n);
    for (var q = 0; q < n; q++) { S.r[q] = 1; S.e[q] = 1 - S.c[q]; }
    try { S.met = LC.stepMetrics(sr.t, sr.y); } catch (e) { S.met = null; }
    S.marginal = !!(m && m.marginal);
    S.cursor = null;
    return true;
  }

  function startSweep(from) {
    cancelAnimationFrame(raf);
    var base = (from > 0 && from < 1) ? from : 0;
    S.progress = base;
    S.paused = false;
    var btn = $('scopeRun');
    if (btn) btn.textContent = '暂停';
    var t0 = performance.now() - base * 700;
    function tick(now) {
      if (S.paused) return;
      S.progress = Math.min(1, (now - t0) / 700);
      draw();
      if (S.progress < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
  }

  function setVisible(v) {
    if (!CARD) return;
    CARD.hidden = !v;
    if (!v) cancelAnimationFrame(raf);
  }

  function update(model) {
    if (!CARD) return;
    if (!model || !model.cl_den || !model.cl_den.length || model.cl_den.length < 3) {
      S.model = null;
      setVisible(false);
      return;
    }
    S.model = model;
    var lw = window.LiveWorkbench;
    S.gain = (lw && lw.state) ? (lw.state().gain || 1) : 1;
    setVisible(true);
    requestAnimationFrame(function () {
      if (!S.model || S.model !== model) return;
      if (!size()) { setTimeout(function () { update(model); }, 60); return; }
      if (!rebuild()) return;
      startSweep();
      updateRead();
    });
  }

  function bind() {
    CARD = $('scopeCard');
    CV = $('scopeCv');
    if (!CARD || !CV) return;

    window.addEventListener('livegain', function (ev) {
      if (CARD.hidden || !S.model) return;
      var g = ev && ev.detail && ev.detail.gain;
      if (!g || Math.abs(g - S.gain) < 1e-9) return;
      S.gain = g;
      if (!rebuild()) return;
      startSweep();
      updateRead();
    });

    var sp = $('scopeSpan');
    if (sp) sp.addEventListener('change', function () {
      S.span = parseFloat(sp.value) || 1;
      if (CARD.hidden || !rebuild()) return;
      startSweep();
      updateRead();
    });

    var run = $('scopeRun');
    if (run) run.addEventListener('click', function () {
      if (CARD.hidden) return;
      S.paused = !S.paused;
      run.textContent = S.paused ? '继续' : '暂停';
      if (!S.paused) startSweep(S.progress >= 1 ? 0 : S.progress);
    });

    var reset = $('scopeReset');
    if (reset) reset.addEventListener('click', function () {
      if (CARD.hidden) return;
      startSweep();
    });

    var toggles = [
      ['scopeChR', 'showR'], ['scopeChC', 'showC'], ['scopeChE', 'showE']
    ];
    toggles.forEach(function (pair) {
      var el = $(pair[0]);
      if (!el) return;
      el.addEventListener('change', function () {
        S[pair[1]] = el.checked;
        draw();
      });
    });

    CV.addEventListener('pointerdown', function (e) {
      if (!S.n) return;
      CV.setPointerCapture(e.pointerId);
      moveCursor(e);
    });
    CV.addEventListener('pointermove', function (e) {
      if (!S.n) return;
      if (e.pointerType === 'touch' && !e.buttons) return;
      moveCursor(e);
    });
    CV.addEventListener('pointerleave', function () {
      if (S.cursor == null) return;
      S.cursor = null;
      updateRead();
      draw();
    });

    window.addEventListener('resize', function () {
      clearTimeout(window.__scopeRz);
      window.__scopeRz = setTimeout(function () {
        if (CARD.hidden) return;
        if (size()) draw();
      }, 140);
    });
  }

  function moveCursor(e) {
    var box = plotBox();
    var rect = CV.getBoundingClientRect();
    var x = e.clientX - rect.left;
    if (x < box.l || x > box.r) { S.cursor = null; updateRead(); draw(); return; }
    var t = (x - box.l) / box.w * S.tMax;
    S.cursor = nearestIndex(t);
    updateRead();
    draw();
  }

  bind();
  window.ScopeWorkbench = { update: update, state: function () { return { span: S.span, tMax: S.tMax }; } };
})();
