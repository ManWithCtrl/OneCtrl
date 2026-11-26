const $ = id => document.getElementById(id);
const root = document.documentElement;

/* ---------- 主题 ---------- */
(function(){
  const q0 = new URLSearchParams(location.search);
  const forced = q0.get('theme');
  if (forced === 'dark' || forced === 'light') root.dataset.theme = forced;
  else {
    const saved = localStorage.getItem('cc-theme');
    if (saved) root.dataset.theme = saved;
  }
  $('theme').onclick = () => {
    const dark = root.dataset.theme
      ? root.dataset.theme === 'dark'
      : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    localStorage.setItem('cc-theme', root.dataset.theme);
  };
})();

/* ---------- 页面切换 ---------- */
const VIEWS = ['analysis', 'tools'];
function setView(v, push){
  if (!VIEWS.includes(v)) v = 'analysis';
  VIEWS.forEach(x => { const el = $('view-' + x); if (el) el.hidden = x !== v; });
  document.querySelectorAll('#nav .chip').forEach(b =>
    b.classList.toggle('on', b.dataset.view === v));
  window.scrollTo(0, 0);
  if (v === 'analysis' && $('fxCard') && !$('fxCard').hidden)
    requestAnimationFrame(() => syncFxOverflow());
  if (push) history.pushState(null, '', location.pathname + location.search + '#/' + v);
}
function initView(){
  let h = (location.hash || '').replace(/^#\/?/, '');
  if (h === 'formula') h = 'analysis';
  setView(VIEWS.includes(h) ? h : 'analysis', false);
  document.querySelectorAll('#nav .chip').forEach(b => b.onclick = () => setView(b.dataset.view, true));
  window.addEventListener('popstate', () => {
    const hh = (location.hash || '').replace(/^#\/?/, '');
    setView(VIEWS.includes(hh) ? hh : 'analysis', false);
  });
}

function msg(t, cls){ const m=$('msg'); m.textContent = t||''; m.className = cls||''; }
function esc(s){ return String(s==null?'':s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function fmt(x, nd){
  if (x===null || x===undefined) return '—';
  if (typeof x === 'number'){
    if (!isFinite(x)) return '∞';
    const a = Math.abs(x);
    if (a < 5e-5) return '0';        // 数值噪声归零（如 -4.16e-17）
    if (a >= 1e6 || a < 1e-4) return x.toExponential(2);
    let str = a >= 1000 ? x.toFixed(0) : a >= 100 ? x.toFixed(1)
            : a >= 10 ? x.toFixed(nd==null?2:nd) : a >= 1 ? x.toFixed(nd==null?2:nd)
            : x.toFixed(Math.min(4, (nd==null?2:nd)+2));
    if (Math.abs(parseFloat(str)) >= 1000){
      const neg = str.startsWith('-');
      str = (neg?'-':'') + Number(str).toLocaleString('en-US');
    }
    return str;
  }
  return String(x);
}

/* ---------- 指标卡 ---------- */
function tile(t){
  const d = t.delta;
  let dtag = '';
  if (d !== null && d !== undefined && Math.abs(d) > 0.0005){
    const good = t.good === 'up' ? d > 0 : t.good === 'down' ? d < 0 : null;
    const cls = good === null ? 'flat' : (good ? 'up-good' : 'down-bad');
    const sign = d > 0 ? '+' : '';
    dtag = `<span class="delta ${cls}">${sign}${fmt(d, 2)}${esc(t.unit||'')}</span>`;
  }
  const was = (t.before !== null && t.before !== undefined && t.hasCmp)
    ? `<div class="was">校正前 <s>${fmt(t.before, 2)}${esc(t.unit||'')}</s></div>` : '';
  return `<div class="tile">
    <div class="k">${t.label}</div>
    <div class="v">${fmt(t.after, 2)}<small>${esc(t.unit||'')}</small>${dtag}</div>
    ${was}
  </div>`;
}

/* ---------- 公式回显 ---------- */
let FX = null, FXMODE = 'factor', FREQ_DATA = null, NYQ_ZOOM = 1;
function renderFormula(f){
  FX = (f && f.rows && f.rows.length) ? f : null;
  FREQ_DATA = (f && f.data) ? f.data : null;
  const card = $('fxCard'), empty = $('fxEmpty');
  if (!FX){
    card.hidden = true;
    if (empty) empty.hidden = false;
    freqOut();
    return;
  }
  card.hidden = false;
  if (empty) empty.hidden = true;
  $('fxNote').textContent = f.note || '';
  $('fxSrc').textContent = f.src || '';
  paintFormula();
  freqOut();
}
function paintFormula(){
  if (!FX) return;
  const key = FXMODE === 'poly' ? 'poly' : 'math';
  $('fxBody').innerHTML = FX.rows.map(r =>
    `<div class="fx-row">
       <div class="fx-label">${esc(r.label)}</div>
       <div class="fx-more" hidden>↔ 左右滑动查看完整公式</div>
       <div class="fx-math">${r[key] || ''}</div>
       <div class="fx-note">${esc(r.note || '')}</div>
     </div>`).join('');
  requestAnimationFrame(() => requestAnimationFrame(syncFxOverflow));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(syncFxOverflow);
}
function syncFxOverflow(){
  if (!FX) return;
  $('fxBody').querySelectorAll('.fx-row').forEach(row => {
    const m = row.querySelector('.fx-math'), more = row.querySelector('.fx-more');
    if (m && more) more.hidden = m.scrollWidth <= m.clientWidth + 2;
  });
}

/* ---------- 工具箱 ---------- */
function numv(id, dv){
  const v = parseFloat(($(id) || {}).value);
  return isFinite(v) ? v : dv;
}
function sig(x, n){
  if (!isFinite(x)) return '—';
  let s = Number(x).toPrecision(n || 4);
  if (s.indexOf('e') >= 0 || s.indexOf('E') >= 0) s = Number(s).toFixed(6);
  if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s;
}
function kv(rows){
  return rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('');
}

function clamp(v, a, b){ return Math.min(b, Math.max(a, v)); }
function frac(n, d){
  return `<span class="mfrac"><span class="mnum">${n}</span><span class="mden">${d}</span></span>`;
}
function calcRows(rows){
  if (!rows || !rows.length) return '';
  return '<div class="calc-title">计算依据</div>' + rows.map(r => {
    const [sym, f, sub, val] = r;
    return `<div class="calc-row"><div class="ci">${sym}</div><div class="ce">` +
      `<span class="cf">= ${f}</span>` +
      (sub ? `<span class="cs">= ${sub}</span>` : '') +
      (val !== undefined && val !== null && val !== '' ? `<span class="cv">→ <b>${val}</b></span>` : '') +
      '</div></div>';
  }).join('');
}

/* 二阶主导极点近似：频域 ↔ 时域 */
function wbRatio(z){
  const q = 1 - 2*z*z;
  return Math.sqrt(Math.max(0, q + Math.sqrt(q*q + 1)));
}
function pmOf(z){
  return 180/Math.PI*Math.atan(2*z/Math.sqrt(Math.sqrt(1 + 4*Math.pow(z, 4)) - 2*z*z));
}
function mrOf(z){
  return (z > 0 && z < Math.SQRT1_2) ? 1/(2*z*Math.sqrt(1 - z*z)) : NaN;
}
function deltaOf(z){
  return (z > 0 && z < 1) ? 100*Math.exp(-Math.PI*z/Math.sqrt(1 - z*z)) : NaN;
}
function zetaFromDelta(p){
  const l = Math.log(Math.max(1e-6, p/100));
  return Math.sqrt(l*l/(Math.PI*Math.PI + l*l));
}
function zetaFromMr(db){
  const m = Math.pow(10, db/20);
  if (!(m > 1)) return NaN;
  return Math.sqrt((1 - Math.sqrt(1 - 1/(m*m)))/2);
}
function zetaFromPm(pm){
  if (!(pm > 0)) return NaN;
  let lo = 0.0001, hi = 1.0;
  if (pmOf(hi) < pm) return pm > 80 ? NaN : 1.0;
  for (let i = 0; i < 48; i++){
    const mid = (lo + hi)/2;
    if (pmOf(mid) < pm) lo = mid; else hi = mid;
  }
  return (lo + hi)/2;
}

function secondOut(){
  const z = clamp(numv('t-zeta', 0.5), 0.001, 1.5);
  const wn = Math.max(0.001, numv('t-wn', 10));
  const s2 = Math.sqrt(Math.max(0, 1 - z*z));
  const under = z < 1;
  const sigma = under ? 100*Math.exp(-Math.PI*z/s2) : 0;
  const tp = under ? Math.PI/(wn*s2) : NaN;
  const tr = under ? (Math.PI - Math.acos(z))/(wn*s2) : NaN;
  const ts = 4/(z*wn);
  const pm = pmOf(z);
  const wb = wn*wbRatio(z);
  const mr = mrOf(z);
  const mrDb = isFinite(mr) ? 20*Math.log10(mr) : NaN;

  $('t-second-out').innerHTML = kv([
    ['带宽 ω<sub>b</sub>', fmt(wb, 3) + ' rad/s'],
    ['谐振峰值 M<sub>r</sub>', isFinite(mrDb) ? fmt(mrDb, 2) + ' dB' : '—'],
    ['相角裕度 γ', fmt(pm, 1) + '°'],
    ['超调量 δ', under ? fmt(sigma, 2) + ' %' : '0 %'],
    ['峰值时间 t<sub>p</sub>', isFinite(tp) ? fmt(tp*1000, 1) + ' ms' : '—'],
    ['上升时间 t<sub>r</sub>', isFinite(tr) ? fmt(tr*1000, 1) + ' ms' : '—'],
    ['调节时间 t<sub>s</sub>(2%)', fmt(ts*1000, 1) + ' ms'],
  ]);

  const zs = sig(z), ws = sig(wn);
  const rows = [];
  rows.push(['ω<sub>b</sub>', 'ω<sub>n</sub>√(1−2ζ²+√((1−2ζ²)²+1))',
    `${ws}×√(1−2×${zs}²+√((1−2×${zs}²)²+1))`, fmt(wb, 3) + ' rad/s']);
  rows.push(['γ', 'atan(2ζ/√(√(1+4ζ⁴)−2ζ²))',
    `atan(2×${zs}/√(√(1+4×${zs}⁴)−2×${zs}²))`, fmt(pm, 1) + '°']);
  if (isFinite(mr)){
    rows.push(['M<sub>r</sub>', frac('1', '2ζ√(1−ζ²)'),
      frac('1', `2×${zs}×√(1−${zs}²)`), fmt(mr, 3) + '（' + fmt(mrDb, 2) + ' dB）']);
  }
  rows.push(['t<sub>s</sub>', frac('4', 'ζω<sub>n</sub>'),
    frac('4', `${zs}×${ws}`), fmt(ts*1000, 1) + ' ms']);
  if (under){
    rows.push(['δ%', 'e<sup>−πζ/√(1−ζ²)</sup>×100%',
      `e<sup>−π×${zs}/√(1−${zs}²)</sup>×100%`, fmt(sigma, 2) + ' %']);
    rows.push(['t<sub>p</sub>', frac('π', 'ω<sub>n</sub>√(1−ζ²)'),
      frac('π', `${ws}×√(1−${zs}²)`), fmt(tp*1000, 1) + ' ms']);
    rows.push(['t<sub>r</sub>', frac('π−acos ζ', 'ω<sub>n</sub>√(1−ζ²)'),
      frac(`π−acos(${zs})`, `${ws}×√(1−${zs}²)`), fmt(tr*1000, 1) + ' ms']);
  }
  $('t-second-fx').innerHTML = calcRows(rows);

  const sg = Math.min(99, Math.max(0.1, numv('t-sigma', 16.3)))/100;
  const l = Math.log(sg);
  const z2 = Math.sqrt(l*l/(Math.PI*Math.PI + l*l));
  $('t-zeta-inv').textContent = fmt(z2, 3);
  $('t-sigma-fx').innerHTML = calcRows([
    ['ζ', '|ln(σ/100)| / √(π²+ln²(σ/100))',
      `|ln(${sig(sg)})| / √(π²+ln²(${sig(sg)}))`, fmt(z2, 3)],
  ]);
}

let LL_EXPR = '';
function coefS(c){ return Math.abs(c - 1) < 1e-9 ? '' : sig(c); }
function llOut(){
  const lead = ($('t-mode').value !== 'lag');
  const deg = clamp(numv('t-phi', 40), 1, 80);
  const phi = deg*Math.PI/180;
  const wm = Math.max(0.01, numv('t-wm', 10));
  const a = (1 + Math.sin(phi))/(1 - Math.sin(phi));
  const T = 1/(wm*Math.sqrt(a));
  const aCoef = Math.sqrt(a)/wm;
  const wz = lead ? wm/Math.sqrt(a) : wm*Math.sqrt(a);
  const wp = lead ? wm*Math.sqrt(a) : wm/Math.sqrt(a);
  const expr = lead
    ? `(${sig(aCoef)}s+1)/(${sig(T)}s+1)`
    : `(${sig(T)}s+1)/(${sig(aCoef)}s+1)`;
  LL_EXPR = expr;

  $('t-ll-out').innerHTML = kv([
    [lead ? 'α' : 'β', fmt(a, 3)],
    ['零点转折频率', fmt(wz, 3) + ' rad/s'],
    ['极点转折频率', fmt(wp, 3) + ' rad/s'],
    ['最大相角', (lead ? '+' : '−') + fmt(deg, 1) + '°'],
    [lead ? '高频增益' : '高频衰减', fmt(lead ? a : 1/a, 3) + ' ×'],
  ]);

  const nCo = lead ? aCoef : T, dCo = lead ? T : aCoef;
  $('t-ll-gc').innerHTML =
    `<div class="tool-expr"><span class="gcl">Gc(s) =</span>${frac(
      `(${coefS(nCo)}s+1)`, `(${coefS(dCo)}s+1)`) }</div>`;

  const an = lead ? 'α' : 'β', as = sig(a), ws = sig(wm);
  const rows = [];
  rows.push([an, '(1+sin|φ<sub>m</sub>|)/(1−sin|φ<sub>m</sub>|)',
    `(1+sin${sig(deg)}°)/(1−sin${sig(deg)}°)`, fmt(a, 3)]);
  rows.push(['T', `1/(ω<sub>m</sub>√${an})`, `1/(${ws}×√${as})`, sig(T)]);
  rows.push(['ω<sub>z</sub>', lead ? 'ω<sub>m</sub>/√α' : 'ω<sub>m</sub>√β',
    lead ? `${ws}/√${as}` : `${ws}×√${as}`, fmt(wz, 3) + ' rad/s']);
  rows.push(['ω<sub>p</sub>', lead ? 'ω<sub>m</sub>√α' : 'ω<sub>m</sub>/√β',
    lead ? `${ws}×√${as}` : `${ws}/√${as}`, fmt(wp, 3) + ' rad/s']);
  $('t-ll-fx').innerHTML = calcRows(rows);
}

function essOut(){
  const K = Math.max(0.01, numv('t-k', 10));
  const rows = [
    ['0 型', fmt(K, 2), '0', '0', fmt(1/(1+K), 2), '&infin;', '&infin;'],
    ['I 型', '&infin;', fmt(K, 2), '0', '0', fmt(1/K, 2), '&infin;'],
    ['II 型', '&infin;', '&infin;', fmt(K, 2), '0', '0', fmt(1/K, 2)],
  ];
  $('t-ess').innerHTML =
    '<tr><th>型别</th><th>K<sub>p</sub></th><th>K<sub>v</sub></th><th>K<sub>a</sub></th>' +
    '<th>阶跃</th><th>斜坡</th><th>加速度</th></tr>' +
    rows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('');
  $('t-ess-fx').innerHTML = calcRows([
    ['K<sub>p</sub>', 'lim<sub>s→0</sub> G(s)', `0 型取 K = ${sig(K)}`, fmt(K, 2)],
    ['K<sub>v</sub>', 'lim<sub>s→0</sub> sG(s)', `I 型取 K = ${sig(K)}`, fmt(K, 2)],
    ['K<sub>a</sub>', 'lim<sub>s→0</sub> s²G(s)', `II 型取 K = ${sig(K)}`, fmt(K, 2)],
    ['e<sub>ss,step</sub>', frac('1', '1+K<sub>p</sub>'),
      `0 型：1/(1+${sig(K)})`, fmt(1/(1+K), 4)],
    ['e<sub>ss,ramp</sub>', frac('1', 'K<sub>v</sub>'),
      `I 型：1/${sig(K)}`, fmt(1/K, 4)],
    ['e<sub>ss,accel</sub>', frac('1', 'K<sub>a</sub>'),
      `II 型：1/${sig(K)}`, fmt(1/K, 4)],
  ]);
}

/* 频域指标 ↔ 时域指标的换算 */
const CONV = {
  zw: ['阻尼比 ζ（ξ）', '自然频率 ω<sub>n</sub> (rad/s)', 0.5, 10],
  mw: ['谐振峰值 M<sub>r</sub> (dB)', '带宽 ω<sub>b</sub> (rad/s)', 1.25, 15.5],
  gw: ['相角裕度 γ (°)', '带宽 ω<sub>b</sub> (rad/s)', 51.8, 15.5],
  sd: ['调节时间 t<sub>s</sub>(2%) (ms)', '超调量 δ (%)', 800, 16.3],
  pd: ['峰值时间 t<sub>p</sub> (ms)', '超调量 δ (%)', 362, 16.3],
};
function convDefaults(){
  const c = CONV[$('c-mode').value] || CONV.zw;
  $('c-x-lab').innerHTML = c[0];
  $('c-y-lab').innerHTML = c[1];
  $('c-x').value = c[2];
  $('c-y').value = c[3];
}
function convOut(){
  const m = $('c-mode').value;
  const x = numv('c-x', 1), y = numv('c-y', 1);
  let z = NaN, wn = NaN, inv = null;
  if (m === 'zw'){
    z = clamp(x, 0.001, 1.5); wn = Math.max(0.001, y);
  } else if (m === 'mw'){
    z = zetaFromMr(x);
    if (isFinite(z)){
      wn = Math.max(0.001, y/wbRatio(z));
      inv = ['ζ', '由 M<sub>r</sub> 反算：√((1−√(1−1/M<sub>r</sub>²))/2)',
        `M<sub>r</sub> = ${sig(x)} dB = ${sig(Math.pow(10, x/20))}`, fmt(z, 4)];
    }
  } else if (m === 'gw'){
    z = zetaFromPm(x);
    if (isFinite(z)) wn = Math.max(0.001, y/wbRatio(z));
    if (isFinite(z)){
      inv = ['ζ', '由 γ 反算：pmOf(ζ) = γ 的根',
        `γ = ${sig(x)}°`, fmt(z, 4)];
    }
  } else if (m === 'sd'){
    z = zetaFromDelta(y);
    if (isFinite(z) && x > 0){
      wn = 4/(z*(x/1000));
      inv = ['ζ', '由 δ 反算：|ln(δ/100)|/√(π²+ln²(δ/100))',
        `δ = ${sig(y)}%`, fmt(z, 4)];
    }
  } else if (m === 'pd'){
    z = zetaFromDelta(y);
    if (isFinite(z) && z < 1 && x > 0){
      wn = Math.PI/((x/1000)*Math.sqrt(1 - z*z));
      inv = ['ζ', '由 δ 反算：|ln(δ/100)|/√(π²+ln²(δ/100))',
        `δ = ${sig(y)}%`, fmt(z, 4)];
    }
  }
  if (!isFinite(z) || !isFinite(wn) || wn <= 0){
    $('c-out').innerHTML = '<div class="tool-bad">这组数值没有对应的二阶指标：M<sub>r</sub> 需 &gt; 1，δ 需在 0–100% 之间，γ 需在 0–76° 之间。</div>';
    $('c-fx').innerHTML = '';
    return;
  }
  const wb = wn*wbRatio(z), mr = mrOf(z);
  const mrDb = isFinite(mr) ? 20*Math.log10(mr) : NaN;
  const pm = pmOf(z), ts = 4/(z*wn);
  const tp = z < 1 ? Math.PI/(wn*Math.sqrt(1 - z*z)) : NaN;
  const tr = z < 1 ? (Math.PI - Math.acos(z))/(wn*Math.sqrt(1 - z*z)) : NaN;
  const de = deltaOf(z);

  $('c-out').innerHTML = kv([
    ['阻尼比 ζ', fmt(z, 4)],
    ['自然频率 ω<sub>n</sub>', fmt(wn, 3) + ' rad/s'],
    ['带宽 ω<sub>b</sub>', fmt(wb, 3) + ' rad/s'],
    ['谐振峰值 M<sub>r</sub>', isFinite(mrDb) ? fmt(mrDb, 2) + ' dB' : '—'],
    ['相角裕度 γ', fmt(pm, 1) + '°'],
    ['调节时间 t<sub>s</sub>(2%)', fmt(ts*1000, 1) + ' ms'],
    ['峰值时间 t<sub>p</sub>', isFinite(tp) ? fmt(tp*1000, 1) + ' ms' : '—'],
    ['上升时间 t<sub>r</sub>', isFinite(tr) ? fmt(tr*1000, 1) + ' ms' : '—'],
    ['超调量 δ', isFinite(de) ? fmt(de, 2) + ' %' : '—'],
  ]);

  const zs = sig(z), ws = sig(wn);
  const rows = [];
  if (inv) rows.push(inv);
  rows.push(['ω<sub>b</sub>', 'ω<sub>n</sub>√(1−2ζ²+√((1−2ζ²)²+1))',
    `${ws}×√(1−2×${zs}²+√((1−2×${zs}²)²+1))`, fmt(wb, 3) + ' rad/s']);
  rows.push(['γ', 'atan(2ζ/√(√(1+4ζ⁴)−2ζ²))',
    `atan(2×${zs}/√(√(1+4×${zs}⁴)−2×${zs}²))`, fmt(pm, 1) + '°']);
  if (isFinite(mr)){
    rows.push(['M<sub>r</sub>', frac('1', '2ζ√(1−ζ²)'),
      frac('1', `2×${zs}×√(1−${zs}²)`), fmt(mrDb, 2) + ' dB']);
  }
  rows.push(['t<sub>s</sub>', frac('4', 'ζω<sub>n</sub>'),
    frac('4', `${zs}×${ws}`), fmt(ts*1000, 1) + ' ms']);
  if (isFinite(tp)){
    rows.push(['t<sub>p</sub>', frac('π', 'ω<sub>n</sub>√(1−ζ²)'),
      frac('π', `${ws}×√(1−${zs}²)`), fmt(tp*1000, 1) + ' ms']);
  }
  if (isFinite(de)){
    rows.push(['δ%', 'e<sup>−πζ/√(1−ζ²)</sup>×100%',
      `e<sup>−π×${zs}/√(1−${zs}²)</sup>×100%`, fmt(de, 2) + ' %']);
  }
  $('c-fx').innerHTML = calcRows(rows);
}

/* s ↔ z 映射 */
function zDirLabels(){
  const d = $('z-dir').value;
  $('z-a-lab').textContent = d === 's2z' ? '实部 σ' : 'Re z';
  $('z-b-lab').textContent = d === 's2z' ? '虚部 ω (rad/s)' : 'Im z';
}
function zOut(){
  const dir = $('z-dir').value;
  const T = Math.max(1e-6, numv('z-T', 0.1));
  const a = numv('z-a', -2), b = numv('z-b', 3);

  if (dir === 's2z'){
    const mag = Math.exp(a*T), ang = b*T;
    const re = mag*Math.cos(ang), im = mag*Math.sin(ang);
    const stable = mag < 1;
    $('z-out').innerHTML = kv([
      ['|z|', sig(mag)],
      ['∠z', `${sig(ang)} rad = ${fmt(ang*180/Math.PI, 1)}°`],
      ['z', `${sig(re)} ${im < 0 ? '−' : '+'} j${sig(Math.abs(im))}`],
      ['稳定性', stable ? '|z| &lt; 1，映射到单位圆内' : '|z| ≥ 1，映射到单位圆外'],
    ]);
    $('z-expr').innerHTML =
      `<span class="tool-expr-inline">z = e<sup>sT</sup> = e<sup>(${sig(a)}${b < 0 ? '−' : '+'}j${sig(Math.abs(b))})×${sig(T)}</sup> = ${sig(mag)}∠${fmt(ang, 4)}</span>`;
    $('z-fx').innerHTML = calcRows([
      ['|z|', 'e<sup>σT</sup>', `e<sup>${sig(a)}×${sig(T)}</sup>`, sig(mag)],
      ['∠z', 'ωT', `${sig(b)}×${sig(T)}`, `${sig(ang)} rad`],
      ['z', '|z|(cos∠z + j sin∠z)',
        `${sig(mag)}(cos${sig(ang)} + j sin${sig(ang)})`,
        `${sig(re)} ${im < 0 ? '−' : '+'} j${sig(Math.abs(im))}`],
      ['判稳', '|z| &lt; 1 ⇔ σ &lt; 0', `|z| = ${sig(mag)}`, stable ? '稳定' : '不稳定'],
    ]);
  } else {
    const mag = Math.hypot(a, b), ang = Math.atan2(b, a);
    if (!(mag > 0)){
      $('z-out').innerHTML = '<div class="tool-bad">z = 0 时对数映射无定义。</div>';
      $('z-expr').innerHTML = '';
      $('z-fx').innerHTML = '';
      return;
    }
    const sigma = Math.log(mag)/T, omega = ang/T;
    const stable = sigma < 0;
    $('z-out').innerHTML = kv([
      ['|z|', sig(mag)],
      ['∠z', `${sig(ang)} rad = ${fmt(ang*180/Math.PI, 1)}°`],
      ['σ', `${sig(sigma)}`],
      ['ω', `${sig(omega)} rad/s`],
      ['s', `${sig(sigma)} ${omega < 0 ? '−' : '+'} j${sig(Math.abs(omega))}`],
      ['稳定性', stable ? 'σ &lt; 0，左半平面' : 'σ ≥ 0，不在左半平面'],
    ]);
    $('z-expr').innerHTML =
      `<span class="tool-expr-inline">s = ln z / T = ln(${sig(mag)}∠${sig(ang)}) / ${sig(T)} = ${sig(sigma)} ${omega < 0 ? '−' : '+'} j${sig(Math.abs(omega))}</span>`;
    $('z-fx').innerHTML = calcRows([
      ['|z|', '√(a²+b²)', `√(${sig(a)}²+${sig(b)}²)`, sig(mag)],
      ['∠z', 'atan2(b, a)', `atan2(${sig(b)}, ${sig(a)})`, `${sig(ang)} rad`],
      ['σ', 'ln|z| / T', `ln(${sig(mag)}) / ${sig(T)}`, sig(sigma)],
      ['ω', '∠z / T', `${sig(ang)} / ${sig(T)}`, `${sig(omega)} rad/s`],
      ['判稳', '|z| &lt; 1 ⇔ σ &lt; 0', `|z| = ${sig(mag)}`, stable ? '稳定' : '不稳定'],
    ]);
  }
}

/* 频率响应：由当前分析结果的系数直接算 G(jω) */
function evalPolyC(c, xr, xi){
  let re = 0, im = 0;
  for (let k = 0; k < c.length; k++){
    const nr = re*xr - im*xi + c[k];
    const ni = re*xi + im*xr;
    re = nr; im = ni;
  }
  return [re, im];
}
function cpx(re, im){
  return `${sig(re)} ${im < 0 ? '−' : '+'} j${sig(Math.abs(im))}`;
}
/* 期望特性法（综合法）中频段估算 */
function expectOut(){
  const out = $('e-out'); if (!out) return;
  const H = numv('e-H', 5), wc = Math.max(1e-6, numv('e-wc', 100));
  if (!(H > 1)){
    out.innerHTML = '<div class="tool-bad">H 需大于 1（按 H=ω₃/ω₂）。若你的定义是 ω₂/ω₃，请输入它的倒数。</div>';
    $('e-fx').innerHTML = '';
    return;
  }
  const w2 = 2*wc/(H+1);
  const w3 = 2*H*wc/(H+1);
  const g = Math.atan(wc/w2) - Math.atan(wc/w3);
  const gd = g*180/Math.PI;
  const sg = Math.sin(g);
  const Mr = sg > 1e-6 ? 1/sg : Infinity;
  const MrDb = isFinite(Mr) ? 20*Math.log10(Mr) : Infinity;
  out.innerHTML = kv([
    ['ω₂', sig(w2) + ' rad/s'],
    ['ω₃', sig(w3) + ' rad/s'],
    ['相角裕度 γ', fmt(gd, 1) + '°'],
    ['谐振峰值 Mr', isFinite(Mr) ? `${fmt(Mr, 2)}（${fmt(MrDb, 2)} dB）` : '∞'],
    ['中频带宽 H', fmt(H, 2)],
    ['带宽比 ω₂/ω₃', fmt(1/H, 3)],
  ]);
  $('e-fx').innerHTML = calcRows([
    ['ω₂', '2ωc / (H+1)', `2×${sig(wc)} / (${sig(H)}+1)`, sig(w2) + ' rad/s'],
    ['ω₃', '2Hωc / (H+1)', `2×${sig(H)}×${sig(wc)} / (${sig(H)}+1)`, sig(w3) + ' rad/s'],
    ['γ', 'arctan(ωc/ω₂) − arctan(ωc/ω₃)',
      `arctan(${sig(wc/w2)}) − arctan(${sig(wc/w3)})`, fmt(gd, 2) + '°'],
    ['M<sub>r</sub>', '1 / sin γ', `1 / sin(${fmt(gd, 2)}°)`,
      isFinite(Mr) ? `${fmt(Mr, 3)}（${fmt(MrDb, 2)} dB）` : '∞'],
  ]);
}

function freqOut(){
  const out = $('f-out'); if (!out) return;
  const w = Math.max(0, numv('f-w', 10));
  const hz = w/(2*Math.PI);
  if ($('f-hz')) $('f-hz').textContent = fmt(hz, 4);
  if (!FREQ_DATA){
    out.innerHTML = '<div class="tool-bad">还没有分析结果。先到「分析」页点「开始分析」，这里会使用那一次的传递函数系数。</div>';
    $('f-fx').innerHTML = '';
    return;
  }
  const key = $('f-tf') ? $('f-tf').value : 'L';
  const D = FREQ_DATA, tf = D[key];
  if (!tf){
    out.innerHTML = '<div class="tool-bad">这次分析没有校正环节 Gc（Gc 留空），请选其他传递函数。</div>';
    $('f-fx').innerHTML = '';
    return;
  }
  const T = D.T || 0.1;
  let xr = 0, xi = w;
  if (D.discrete){ xr = Math.cos(w*T); xi = Math.sin(w*T); }
  const [nr, ni] = evalPolyC(tf.num, xr, xi);
  const [dr, di] = evalPolyC(tf.den, xr, xi);
  const nm = Math.hypot(nr, ni), dm = Math.hypot(dr, di);
  if (dm < 1e-13){
    out.innerHTML = `<div class="tool-bad">ω = ${sig(w)} rad/s 落在极点（谐振点）上，|G| → ∞，相角无定义。</div>`;
    $('f-fx').innerHTML = '';
    return;
  }
  const mag = nm/dm;
  const phN = Math.atan2(ni, nr), phD = Math.atan2(di, dr);
  let deg = (phN - phD)*180/Math.PI;
  deg = ((deg + 180)%360 + 360)%360 - 180;
  const re = (nr*dr + ni*di)/(dm*dm);
  const im = (ni*dr - nr*di)/(dm*dm);
  const dB = mag > 0 ? 20*Math.log10(mag) : -Infinity;
  const alias = D.discrete && w*T > Math.PI;
  const gname = D.discrete ? 'G(e<sup>jωT</sup>)' : 'G(jω)';
  const rows = [
    ['|G|', mag > 0 ? sig(mag) : '0'],
    ['|G| (dB)', isFinite(dB) ? fmt(dB, 2) + ' dB' : '−∞ dB'],
    ['∠G', nm > 0 ? fmt(deg, 2) + '°' : '—'],
    [gname, cpx(re, im)],
    ['频率 f', fmt(hz, 4) + ' Hz'],
  ];
  if (alias) rows.push(['提示', 'ωT &gt; π，已超过 Nyquist，结果会混叠']);
  out.innerHTML = kv(rows);

  const calc = [];
  if (D.discrete){
    calc.push(['z', 'e<sup>jωT</sup>', `e<sup>j${sig(w)}×${sig(T)}</sup>`, cpx(xr, xi)]);
  } else {
    calc.push(['ω', '2πf', `${fmt(hz, 4)} × 2π`, `${sig(w)} rad/s`]);
  }
  calc.push(
    [gname, D.discrete ? 'N(z) / D(z)' : 'N(jω) / D(jω)',
      `(${cpx(nr, ni)}) / (${cpx(dr, di)})`, cpx(re, im)],
    ['|G|', '|N| / |D|', `${sig(nm)} / ${sig(dm)}`, sig(mag)],
    ['∠G', '∠N − ∠D', `${fmt(phN*180/Math.PI, 2)}° − (${fmt(phD*180/Math.PI, 2)}°)`, nm > 0 ? `${fmt(deg, 2)}°` : '—'],
    ['dB', '20 log<sub>10</sub>|G|', `20 log<sub>10</sub>(${sig(mag)})`, isFinite(dB) ? `${fmt(dB, 2)} dB` : '−∞ dB'],
  );
  $('f-fx').innerHTML = calcRows(calc);
}


/* ---------- Nyquist 视野 0.1x–10x ---------- */
function nyqSliderToZoom(v){
  const t = (Math.max(10, Math.min(1000, +v || 500)) - 10) / 990;
  return Math.pow(10, -1 + 2 * t);
}
function nyqZoomToSlider(z){
  const t = (Math.log(Math.max(0.1, Math.min(10, z))) / Math.LN10 + 1) / 2;
  return Math.round(10 + 990 * t);
}
function nyqLabel(z){
  return '×' + (z >= 1 ? z.toFixed(1) : z.toFixed(2));
}
function initNyq(){
  const s = $('nyqZoom'), v = $('nyqZoomv');
  if (!s) return;
  s.value = String(nyqZoomToSlider(NYQ_ZOOM));
  if (v) v.textContent = nyqLabel(NYQ_ZOOM);
  s.addEventListener('input', () => {
    NYQ_ZOOM = nyqSliderToZoom(s.value);
    if (v) v.textContent = nyqLabel(NYQ_ZOOM);
  });
  s.addEventListener('change', () => { run(); });
}

function toolInit(){
  document.querySelectorAll('#toolTabs .chip').forEach(b => b.onclick = () => {
    document.querySelectorAll('#toolTabs .chip').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.tool-pane').forEach(p =>
      p.classList.toggle('on', p.id === 'tool-' + b.dataset.tool));
    if (b.dataset.tool === 'freq') freqOut();
    if (b.dataset.tool === 'expect') expectOut();
  });
  ['t-zeta','t-wn','t-sigma'].forEach(id => {
    const el = $(id); if (el) el.addEventListener('input', secondOut);
  });
  ['t-phi','t-wm'].forEach(id => {
    const el = $(id); if (el) el.addEventListener('input', llOut);
  });
  const tm = $('t-mode'); if (tm) tm.addEventListener('change', llOut);
  const tk = $('t-k'); if (tk) tk.addEventListener('input', essOut);
  const cm = $('c-mode');
  if (cm) cm.addEventListener('change', () => { convDefaults(); convOut(); });
  ['c-x','c-y'].forEach(id => {
    const el = $(id); if (el) el.addEventListener('input', convOut);
  });
  const zd = $('z-dir');
  if (zd) zd.addEventListener('change', () => { zDirLabels(); zOut(); });
  ['z-a','z-b','z-T'].forEach(id => {
    const el = $(id); if (el) el.addEventListener('input', zOut);
  });
  const ft = $('f-tf'); if (ft) ft.addEventListener('change', freqOut);
  const fw = $('f-w'); if (fw) fw.addEventListener('input', freqOut);
  ['e-H','e-wc'].forEach(id => {
    const el = $(id); if (el) el.addEventListener('input', expectOut);
  });
  $('t-ll-fill').onclick = () => {
    if (!LL_EXPR) return;
    $('gc').value = LL_EXPR;
    $('T').value = '';
    setView('analysis', true);
    run();
    $('result').scrollIntoView({behavior:'smooth', block:'start'});
  };
  document.querySelectorAll('#fxSwitch .chip').forEach(b => b.onclick = () => {
    FXMODE = b.dataset.fx === 'poly' ? 'poly' : 'factor';
    document.querySelectorAll('#fxSwitch .chip').forEach(x => x.classList.toggle('on', x === b));
    paintFormula();
  });
  secondOut(); llOut(); essOut(); convOut(); zOut(); freqOut(); expectOut();
  let _rz = 0;
  window.addEventListener('resize', () => { clearTimeout(_rz); _rz = setTimeout(syncFxOverflow, 120); });
}

/* ---------- 请求 ---------- */
function restoreSelects(q){
  const pv = q.get('panel'), nv = q.get('nl'), kv = q.get('kind');
  if (kv && $('kind')) $('kind').value = kv;
  if (pv && $('panel')) $('panel').value = pv;
  if (nv && $('nl')) $('nl').value = nv;
}

/* 描述函数法摘要（放在非线性控件下方，避免埋在稳定性卡里） */
function renderDf(df){
  const box = $('dfSummary');
  if (!box) return;
  if (!df){ box.hidden = true; return; }
  box.hidden = false;
  const names = {relay:'理想继电器', relay_dz:'带死区继电器', relay_hyst:'滞环继电器', sat:'饱和'};
  const formulas = {
    relay: 'N(A) = 4M/(πA)',
    relay_dz: 'N(A) = 4M/(πA)·√(1−(a/A)²)',
    relay_hyst: 'N(A) = 4M/(πA)·[√(1−(a/A)²) − j·(a/A)]（复值，−1/N 在 Im = −πa/(4M) 的射线上）',
    sat: 'N(A) = (2/π)[asin(a/A)+(a/A)√(1−(a/A)²)]'
  };
  let nt = '（' + (names[df.kind] || df.kind) + '，M=' + fmt(df.M, 3) + '）';
  if (df.kind !== 'relay') nt = '（' + (names[df.kind] || df.kind) + '，M=' + fmt(df.M, 3) + '，a=' + fmt(df.a, 3) + '）';
  $('dfSummaryNote').textContent = nt;
  const body = $('dfSummaryBody');
  const f = formulas[df.kind] || '';
  if (!df.cycles || !df.cycles.length){
    body.innerHTML = `<div class="df-formula">${esc(f)}</div>` +
      '<div class="df-no">−1/N(A) 与 G(jω) 无有限交点 → 无自振</div>';
    return;
  }
  body.innerHTML = `<div class="df-formula">${esc(f)}</div>` + df.cycles.map(c =>
    `<div>交点：A = <b>${fmt(c.A, 4)}</b>，ω = <b>${fmt(c.w, 4)}</b> rad/s` +
    (c.period ? `，周期 ${fmt(c.period, 3)} s` : '') +
    (df.kind === 'relay_hyst' ? `，G(jω) = ${fmt(c.gRe, 4)} ${c.gIm >= 0 ? '+' : '−'} ${fmt(Math.abs(c.gIm), 4)}j` : '') +
    (c.stable == null ? '' : (c.stable ? ' → <b class="df-good">稳定自振</b>' : ' → <b class="df-bad">不稳定（不会持续）</b>')) +
    '</div>').join('');
}

async function run(){
  const g0 = $('g0').value.trim(), gc = $('gc').value.trim(), T = $('T').value.trim();
  const panel = ($('panel') || {}).value || 'rl';
  const nl = ($('nl') || {}).value || 'none';
  const kind = ($('kind') || {}).value || 'step';
  const nlM = ($('nlM') || {}).value || '1';
  const nla = ($('nla') || {}).value || '1';
  if (!g0){ msg('请先填原开环 G₀', 'err'); $('g0').focus(); return; }
  $('btn').disabled = true; msg('计算中…');
  const t0 = performance.now();
  try{
    const payload = JSON.stringify({g0, gc, T, panel, nl, kind, nlM, nla, nz: NYQ_ZOOM, w: window.innerWidth});
    const ask = async (ms) => {
      const ac = new AbortController();
      const tid = setTimeout(() => ac.abort(), ms);
      try{
        return await fetch('/api', {method:'POST', headers:{'Content-Type':'application/json'},
          body: payload, signal: ac.signal});
      } finally { clearTimeout(tid); }
    };
    let r;
    try{
      r = await ask(120000);
    }catch(e1){
      msg('连接慢，重试一次…');
      r = await ask(120000);      // 隧道抖动时自动重试一次
    }
    const j = await r.json();
    if (!j.ok){ msg('⚠ ' + (j.err||'出错了'), 'err'); return; }
    window.__lastResult = j;

    $('result').hidden = false;
    $('tiles').innerHTML = (j.tiles||[]).map(tile).join('');
    renderFormula(j.formula);
    if (window.LiveWorkbench) LiveWorkbench.update(j.model || null);
    if (window.M4Workbench) M4Workbench.update(j.model || null);
    if (window.ScopeWorkbench) ScopeWorkbench.update(j.model || null);
    if (window.PhaseWorkbench) PhaseWorkbench.update(j.model || null);
    if (window.RootLocus) RootLocus.update(j.model || null);
    if (window.NyquistWorkbench) NyquistWorkbench.update(j.nyq_model || j.model || null);
    if (j.comp && j.comp.length){
      $('compCard').hidden = false;
      $('compNote').textContent = j.domainNote || '';
      $('compBody').innerHTML = j.comp.map(l =>
        /^(零点|极点|直流|增益|转折|只会|高频|多出|其余)/.test(l)
          ? `<div>${esc(l)}</div>` : `<div><b>${esc(l)}</b></div>`).join('');
    } else {
      $('compCard').hidden = true;
    }
    const _fl = $('figLink');
    if (j.img) { $('fig').src = j.img; if (_fl) { _fl.style.display = 'block'; } }
    else if (_fl) { _fl.style.display = 'none'; }
    mountFigs('figsM', 'figLink', j.imgs, j.img_url);
  function mountFigs(boxId, linkId, imgs, url){
    const box = $(boxId), link = $(linkId);
    if (link && url) link.href = url;
    if (box) {
      if (imgs && imgs.length) {
        box.innerHTML = '';
        imgs.forEach((it, i) => {
          const u = (it && it.u) ? it.u : it;
          const d = (it && it.d) ? it.d : it;
          const a = document.createElement('a');
          a.href = u; a.target = '_blank'; a.rel = 'noopener';
          const im = document.createElement('img');
          im.src = d; im.alt = '面板 ' + (i + 1); im.loading = 'lazy';
          a.appendChild(im); box.appendChild(a);
        });
        box.style.display = 'block';
        if (link) link.style.display = 'none';
        return;
      }
      box.style.display = 'none';
      if (link) link.style.display = 'block';
    }
  }
  if (j.stab && (j.stab.img || (j.stab.imgs && j.stab.imgs.length))){
      $('stabCard').hidden = false;
      $('nyqZoomWrap').hidden = /离散/.test(j.mode || '');
      $('fig2').src = j.stab.img;
    mountFigs('stabsM', 'stabLink', j.stab.imgs, j.stab.img_url);
      $('stabNote').textContent = j.stab.marginal ? '闭环临界稳定'
        : (j.stab.stable ? '闭环稳定' : '闭环不稳定');
      $('stabNote').className = j.stab.marginal ? 'warn' : '';
      $('stabText').innerHTML = (j.stab.text||[]).map(l => `<div>${esc(l)}</div>`).join('');
    } else {
      $('stabCard').hidden = true;
    }
    renderDf(j.stab && j.stab.df);
    $('txt').textContent = j.text;
    const ms = Math.round(performance.now()-t0);
    if (j.marginal) msg(`完成 · ${j.mode} · ${ms} ms · ⚠ 闭环临界稳定（含虚轴/原点极点，时域指标不显示）`, 'warn');
    else msg(`完成 · ${j.mode} · ${ms} ms · ${j.stable ? '闭环稳定' : '闭环不稳定'}`, j.stable ? 'ok' : 'err');

    const q = new URLSearchParams({g0, gc, t:T, panel, nl, kind, nlM, nla, nz: NYQ_ZOOM.toFixed(2)});
    history.replaceState(null, '', '?' + q.toString() + (location.hash || ''));
  }catch(e){
    msg('连不上服务：' + e, 'err');
  }finally{
    $('btn').disabled = false;
  }
}

/* ---------- 交互 ---------- */
$('btn').onclick = run;
['g0','gc','T','nlM','nla'].forEach(id => {
  const el = $(id);
  if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
});
document.querySelectorAll('.chips .chip').forEach(c => c.onclick = () => {
  $('g0').value = c.dataset.g0; $('gc').value = c.dataset.gc; $('T').value = c.dataset.t;
  run();
});
toolInit();
initNyq();
initView();

/* 从 URL 恢复 */
(function(){
  const q = new URLSearchParams(location.search);
  if (q.has('g0')) $('g0').value = q.get('g0');
  if (q.has('gc')) $('gc').value = q.get('gc');
  if (q.has('t'))  $('T').value  = q.get('t');
  if (q.has('nz')){
    const z = parseFloat(q.get('nz'));
    if (isFinite(z)) NYQ_ZOOM = Math.max(0.1, Math.min(10, z));
    const s = $('nyqZoom'), v = $('nyqZoomv');
    if (s) s.value = String(nyqZoomToSlider(NYQ_ZOOM));
    if (v) v.textContent = nyqLabel(NYQ_ZOOM);
  }
  restoreSelects(q);
  function syncNl(){
    const v = $('nl') ? $('nl').value : 'none';
    const on = v !== 'none';
    const p = $('nlP'), q = $('nlA'), h = $('nlHint');
    if (p) p.hidden = !(v === 'relay' || v === 'relay_dz' || v === 'relay_hyst');
    if (q) q.hidden = !(v === 'relay_dz' || v === 'relay_hyst' || v === 'sat');
    if (h) h.hidden = !on;
  }
  ['panel','nl','kind','nlM','nla'].forEach(id => {
    const el = $(id); if (el) el.addEventListener('change', () => { syncNl(); run(); });
  });
  syncNl();
  if (q.get('nlM') && $('nlM')) $('nlM').value = q.get('nlM');
  if (q.get('nla') && $('nla')) $('nla').value = q.get('nla');
  if (q.has('g0') || q.has('auto')) setTimeout(run, 80);
  else setTimeout(run, 250);   // 首次打开直接算一遍默认例子
})();

window.addEventListener('DOMContentLoaded', function(){
try{
// ---- 灯箱：点图放大（data: URL 不能直接在新标签页打开）
function makeLightbox(){
  const lb = document.createElement('div');
  lb.className = 'lightbox';
  lb.innerHTML = '<img alt="大图">';
  lb.addEventListener('click', () => { lb.classList.remove('on'); });
  document.body.appendChild(lb);
  return lb;
}
const LB = makeLightbox();
['fig','fig2'].forEach(id => {
  const el = $(id);
  if (!el) return;
  el.style.cursor = 'zoom-in';
  el.addEventListener('click', () => {
    const im = LB.querySelector('img');
    im.src = el.src;
    LB.classList.add('on');
  });
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') LB.classList.remove('on'); });

}catch(e){ console.warn('lightbox init failed', e); }
});
