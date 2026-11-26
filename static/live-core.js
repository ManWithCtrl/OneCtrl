/* 实时联动数值核：纯 JS，无依赖。
 * 只负责连续 LTI 的快速预览；精确值仍以 Python 内核为准。
 * 浏览器挂到 window.LiveCore，Node 下可 require 做回归测试。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LiveCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const C = (re, im) => ({ re: +re || 0, im: +im || 0 });
  const cadd = (a, b) => C(a.re + b.re, a.im + b.im);
  const csub = (a, b) => C(a.re - b.re, a.im - b.im);
  const cmul = (a, b) => C(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re);
  const cdiv = (a, b) => {
    const d = b.re * b.re + b.im * b.im || 1e-30;
    return C((a.re * b.re + a.im * b.im) / d, (a.im * b.re - a.re * b.im) / d);
  };
  const cabs = (a) => Math.hypot(a.re, a.im);
  const carg = (a) => Math.atan2(a.im, a.re);
  const cexp = (a) => C(Math.exp(a.re) * Math.cos(a.im), Math.exp(a.re) * Math.sin(a.im));
  const cpow = (a, n) => {
    let r = C(1, 0);
    for (let i = 0; i < n; i++) r = cmul(r, a);
    return r;
  };

  function trim(c) {
    const a = Array.from(c || [], Number);
    while (a.length > 1 && Math.abs(a[0]) < 1e-14) a.shift();
    return a.length ? a : [0];
  }

  function polyval(c, x) {
    let y = C(0, 0);
    for (let i = 0; i < c.length; i++) y = cadd(cmul(y, x), C(c[i], 0));
    return y;
  }

  function polyadd(a, b) {
    a = trim(a); b = trim(b);
    const n = Math.max(a.length, b.length);
    const out = new Array(n).fill(0);
    for (let i = 0; i < a.length; i++) out[n - a.length + i] += a[i];
    for (let i = 0; i < b.length; i++) out[n - b.length + i] += b[i];
    return trim(out);
  }

  function polymul(a, b) {
    a = trim(a); b = trim(b);
    const out = new Array(a.length + b.length - 1).fill(0);
    for (let i = 0; i < a.length; i++)
      for (let j = 0; j < b.length; j++) out[i + j] += a[i] * b[j];
    return trim(out);
  }

  function polyscale(a, k) {
    return trim(a.map((v) => v * k));
  }

  /* Durand-Kerner：实系数多项式全部复根（降幂）。 */
  function roots(c) {
    c = trim(c);
    if (c.length <= 1) return [];
    if (c.length === 2) return [C(-c[1] / c[0], 0)];
    const n = c.length - 1;
    const a = c.map((v) => v / c[0]);
    const z = [];
    const seed = C(0.4, 0.9);
    for (let k = 0; k < n; k++) z.push(cpow(seed, k + 1));
    for (let it = 0; it < 400; it++) {
      let maxd = 0;
      for (let k = 0; k < n; k++) {
        let den = C(1, 0);
        for (let j = 0; j < n; j++) {
          if (j === k) continue;
          den = cmul(den, csub(z[k], z[j]));
        }
        if (cabs(den) < 1e-18) continue;
        const delta = cdiv(polyval(a, z[k]), den);
        z[k] = csub(z[k], delta);
        maxd = Math.max(maxd, cabs(delta));
      }
      if (maxd < 1e-11) break;
    }
    return z;
  }

  /* 闭环单位负反馈：num/(den+num)。 */
  function closedLoop(num, den) {
    return { num: trim(num), den: polyadd(den, num) };
  }

  /* 可控标准型：H(s)=b(s)/a(s)，a 首一。返回 A,B,C,D。 */
  function tf2ss(num, den) {
    num = trim(num); den = trim(den);
    const n = den.length - 1;
    if (n <= 0) return { A: [], B: [], C: [], D: num[0] / den[0] || 0, n: 0 };
    const a = den.map((v) => v / den[0]);
    const b = new Array(n + 1).fill(0);
    const off = n + 1 - num.length;
    for (let i = 0; i < num.length; i++) b[off + i] = num[i] / den[0];
    const d = b[0];
    const r = new Array(n);
    for (let j = 0; j < n; j++) r[j] = b[j + 1] - d * a[j + 1];
    const A = Array.from({ length: n }, () => new Array(n).fill(0));
    for (let i = 0; i < n - 1; i++) A[i][i + 1] = 1;
    for (let j = 0; j < n; j++) A[n - 1][j] = -a[n - j];
    const B = new Array(n).fill(0); B[n - 1] = 1;
    const Cc = new Array(n);
    for (let j = 0; j < n; j++) Cc[j] = r[n - 1 - j];
    return { A, B, C: Cc, D: d, n };
  }

  function matVec(A, x) {
    const y = new Array(x.length).fill(0);
    for (let i = 0; i < A.length; i++)
      for (let j = 0; j < x.length; j++) y[i] += A[i][j] * x[j];
    return y;
  }

  function stepResponse(num, den, nPts, tEndReq) {
    num = trim(num); den = trim(den);
    const ss = tf2ss(num, den);
    const n = ss.n;
    const want = Math.max(200, Math.min(4000, nPts || 900));
    if (n === 0) {
      const T = (tEndReq && isFinite(tEndReq) && tEndReq > 0) ? tEndReq : 5;
      const t = [], y = [];
      for (let i = 0; i < want; i++) { t.push(i / (want - 1) * T); y.push(ss.D); }
      return { t, y, tEnd: T, ss: ss.D, dt: T / (want - 1) };
    }
    const rs = roots(den);
    let minSig = Infinity, maxAbs = 1;
    for (const z of rs) {
      minSig = Math.min(minSig, -z.re);
      maxAbs = Math.max(maxAbs, Math.hypot(z.re, z.im));
    }
    let tEnd = (tEndReq && isFinite(tEndReq) && tEndReq > 0) ? tEndReq
      : (minSig > 1e-6 ? Math.min(40, Math.max(1, 8 / minSig)) : 6);
    if (!isFinite(tEnd) || tEnd <= 0) tEnd = 6;
    let dt = Math.min(tEnd / (want - 1), 0.18 / maxAbs);
    let N = Math.min(4000, Math.max(want, Math.ceil(tEnd / dt) + 1));
    dt = tEnd / (N - 1);
    const t = new Array(N), y = new Array(N);
    let x = new Array(n).fill(0);
    const f = (xx, u) => {
      const Ax = matVec(ss.A, xx);
      for (let i = 0; i < n; i++) Ax[i] += ss.B[i] * u;
      return Ax;
    };
    for (let i = 0; i < N; i++) {
      const u = 1;
      let out = ss.D * u;
      for (let j = 0; j < n; j++) out += ss.C[j] * x[j];
      t[i] = i * dt; y[i] = out;
      if (i === N - 1) break;
      const k1 = f(x, u);
      const x2 = x.map((v, j) => v + 0.5 * dt * k1[j]);
      const k2 = f(x2, u);
      const x3 = x.map((v, j) => v + 0.5 * dt * k2[j]);
      const k3 = f(x3, u);
      const x4 = x.map((v, j) => v + dt * k3[j]);
      const k4 = f(x4, u);
      x = x.map((v, j) => v + dt / 6 * (k1[j] + 2 * k2[j] + 2 * k3[j] + k4[j]));
    }
    return { t, y, tEnd, ss: ss.D, dt };
  }

  function stepMetrics(t, y) {
    const n = y.length;
    const tail = Math.max(3, Math.floor(n * 0.05));
    let ss = 0;
    for (let i = n - tail; i < n; i++) ss += y[i];
    ss /= tail;
    let peak = -Infinity, tp = null;
    for (let i = 0; i < n; i++) if (y[i] > peak) { peak = y[i]; tp = t[i]; }
    const sigma = Math.abs(ss) > 1e-9 ? (peak - ss) / Math.abs(ss) * 100 : null;
    let ts = 0;
    for (let i = n - 1; i >= 0; i--) {
      if (Math.abs(y[i] - ss) > 0.02 * Math.abs(ss || 1)) { ts = t[i]; break; }
    }
    return { ss, peak, tp, sigma, ts };
  }

  function logspace(wmin, wmax, n) {
    const a = [], r = Math.log(wmax / wmin);
    for (let i = 0; i < n; i++) a.push(wmin * Math.exp(r * i / (n - 1)));
    return a;
  }

  function bode(num, den, nPts) {
    num = trim(num); den = trim(den);
    const rs = roots(num).concat(roots(den));
    let lo = Infinity, hi = 0;
    for (const z of rs) {
      const a = Math.hypot(z.re, z.im);
      if (a > 1e-9) { lo = Math.min(lo, a); hi = Math.max(hi, a); }
    }
    if (!isFinite(lo) || hi <= 0) { lo = 0.1; hi = 100; }
    const wmin = Math.max(1e-3, lo / 100);
    const wmax = Math.min(1e5, Math.max(hi * 100, wmin * 1000));
    const n = nPts || 420;
    const w = logspace(wmin, wmax, n);
    const db = new Array(n), ph = new Array(n);
    let prev = null;
    for (let i = 0; i < n; i++) {
      const s = C(0, w[i]);
      const H = cdiv(polyval(num, s), polyval(den, s));
      db[i] = 20 * Math.log10(Math.max(1e-15, cabs(H)));
      let p = carg(H) * 180 / Math.PI;
      if (prev != null) {
        while (p - prev > 180) p -= 360;
        while (prev - p > 180) p += 360;
      }
      ph[i] = p; prev = p;
    }
    return { w, db, ph };
  }

  /* 渐近幅频：按时间常数折线，返回与 bode 同频点的 dB。 */
  function asymptote(num, den, w) {
    num = trim(num); den = trim(den);
    const zr = roots(num), pr = roots(den);
    const k0 = num[0] / den[0];
    let type = 0;
    let mag = Math.abs(k0);
    const brk = [];
    for (const z of pr) {
      const a = Math.hypot(z.re, z.im);
      if (a < 1e-9) type++;
      else { mag /= a; brk.push({ w: a, s: -20 }); }
    }
    for (const z of zr) {
      const a = Math.hypot(z.re, z.im);
      if (a < 1e-9) type--;
      else { mag *= a; brk.push({ w: a, s: +20 }); }
    }
    brk.sort((x, y) => x.w - y.w);
    const base = 20 * Math.log10(Math.max(1e-15, mag));
    const out = new Array(w.length);
    for (let i = 0; i < w.length; i++) {
      let db = base - 20 * type * Math.log10(w[i]);
      for (const b of brk) {
        if (w[i] > b.w) db += b.s * Math.log10(w[i] / b.w);
      }
      out[i] = db;
    }
    return out;
  }

  function cross(data) {
    const { w, db, ph } = data;
    const out = { wc: null, pm: null, wg: null, gm: null };
    for (let i = 1; i < w.length; i++) {
      if (db[i - 1] >= 0 && db[i] < 0) {
        const f = db[i - 1] / (db[i - 1] - db[i]);
        out.wc = Math.exp(Math.log(w[i - 1]) + f * (Math.log(w[i]) - Math.log(w[i - 1])));
        out.pm = 180 + (ph[i - 1] + f * (ph[i] - ph[i - 1]));
        break;
      }
    }
    for (let i = 1; i < w.length; i++) {
      const a = ph[i - 1] + 180, b = ph[i] + 180;
      if ((a <= 0 && b >= 0) || (a >= 0 && b <= 0)) {
        const f = a / (a - b);
        out.wg = Math.exp(Math.log(w[i - 1]) + f * (Math.log(w[i]) - Math.log(w[i - 1])));
        out.gm = -(db[i - 1] + f * (db[i] - db[i - 1]));
        break;
      }
    }
    return out;
  }

  function nearestIndex(w, val) {
    let best = 0, d = Infinity;
    for (let i = 0; i < w.length; i++) {
      const dd = Math.abs(Math.log(w[i]) - Math.log(val));
      if (dd < d) { d = dd; best = i; }
    }
    return best;
  }

  return {
    C, cadd, csub, cmul, cdiv, cabs, carg,
    trim, polyval, polyadd, polymul, polyscale, roots,
    closedLoop, tf2ss, stepResponse, stepMetrics,
    bode, asymptote, cross, nearestIndex, logspace,
  };
});
