/* 相平面 classify() 的单元测试：从 static/phase.js 里抠出 classify 函数直接跑。
   用法：node _ph_test.js */
const fs = require('fs');

const src = fs.readFileSync(__dirname + '/static/phase.js', 'utf8');
const m = src.match(/function classify\(a1, a2\) \{[\s\S]*?\n  \}/);
if (!m) { console.error('没找到 classify()'); process.exit(1); }
const classify = new Function('return ' + m[0].replace(/^function classify/, 'function'))();

const cases = [
  { a1: 0, a2: 9, want: '中心', stable: false, marginal: true, note: '纯虚根 0±3j' },
  { a1: -2, a2: 9, want: '不稳定焦点', stable: false, marginal: false, note: '实部 +1' },
  { a1: 2, a2: 9, want: '稳定焦点', stable: true, marginal: false, note: '实部 -1' },
  { a1: -3, a2: 2, want: '不稳定结点', stable: false, marginal: false, note: '根 1,2' },
  { a1: 3, a2: 2, want: '稳定结点', stable: true, marginal: false, note: '根 -1,-2' },
  { a1: 0, a2: -9, want: '鞍点', stable: false, marginal: false, note: '实根异号' },
  { a1: 2, a2: 0, want: '原点有根（退化）', stable: false, marginal: false, note: '根 0,-2' },
  { a1: 1e-7, a2: 4, want: '中心', stable: false, marginal: true, note: '数值噪声下的纯虚根' },
];

let fail = 0;
for (const c of cases) {
  const r = classify(c.a1, c.a2);
  const ok = r.type === c.want && r.stable === c.stable && r.marginal === c.marginal;
  if (!ok) fail++;
  console.log((ok ? 'PASS' : 'FAIL') + ' a1=' + c.a1 + ' a2=' + c.a2 + ' -> ' + r.type + ' stable=' + r.stable + ' marginal=' + r.marginal + ' (' + c.note + ')');
}
console.log(fail ? fail + ' 个用例失败' : '全部 ' + cases.length + ' 个用例通过');
process.exit(fail ? 1 : 0);
