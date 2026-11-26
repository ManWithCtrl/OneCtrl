#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ctrl_check.py —— 校正前后一键验算（Bode / 阶跃 / 稳定裕度 / 时域指标）

用法示例
--------
普通表达式（乘号可省略）：
    python ctrl_check.py -g0 "100*(0.1s+1)/((s+1)*(0.2s+1)*(0.02s+1))" \
                         -gc "(s/12.12+1)/(s/70.34+1)"

LaTeX 表达式（$ 可有可无）：
    python ctrl_check.py -g0 "\\frac{10}{s(s+1)}" -gc "\\frac{2s+1}{0.5s+1}"

不校正（只看原系统）：
    python ctrl_check.py -g0 "10/(s(s+1)(s+2))"

输出
----
    ctrl_check.png   四联图（幅频 / 相频 / 阶跃 / 零极点图）
    终端打印         ω_c、γ、K_g、σ、t_p、t_s、ζ、ω_n、稳态误差

约定
----
    * 单位负反馈
    * 时域指标由闭环阶跃响应数值算出（残数法，遇重极点自动退化为 RK4）
    * 阻尼比取闭环主导共轭极点对的 ζ = -Re/|p|
"""

import argparse
import os
import re
import sys

import numpy as np

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.size": 9.5, "axes.linewidth": 0.8, "figure.dpi": 150,
    "mathtext.fontset": "dejavusans",
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

try:
    import sympy as sp
except ImportError:
    sys.exit("需要 sympy：pip install sympy")

s = sp.Symbol("s")


# ---------------------------------------------------------------- 输入解析
def _read_group(text, i):
    """text[i] == '{'，返回 (内容, '}' 之后的索引)"""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
    raise ValueError("花括号不配对：%s" % text)


def _convert_frac(text):
    """把 \\frac{a}{b} / \\dfrac / \\tfrac 递归转成 ((a)/(b))"""
    out, i = [], 0
    while i < len(text):
        m = re.match(r"\\(?:d|t)?frac\s*", text[i:])
        if m:
            k = i + m.end()
            num, k2 = _read_group(text, k)
            while k2 < len(text) and text[k2] in " \t":
                k2 += 1
            den, k3 = _read_group(text, k2)
            out.append("((%s)/(%s))" % (_convert_frac(num), _convert_frac(den)))
            i = k3
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _implicit_mul(text):
    """2s -> 2*s，s( -> s*(，)( -> )*(，2( -> 2*(  （不破坏 **）"""
    text = re.sub(r"(?<=[0-9])(?=[s(])", "*", text)
    text = re.sub(r"(?<=[s])(?=[s(0-9])", "*", text)
    text = re.sub(r"(?<=\))(?=[s(0-9])", "*", text)
    return text


def to_expr(text):
    """把 LaTeX 或普通表达式转成 sympy 表达式（自变量 s）"""
    t = text.strip()
    t = t.replace("$", "").replace("\\[", "").replace("\\]", "")
    t = t.replace("\\left", "").replace("\\right", "")
    t = t.replace("\\!", "").replace("\\,", "").replace("\\;", "")
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    t = t.replace("\\pi", "pi")
    t = _convert_frac(t)
    t = re.sub(r"\\(?:mathrm|text|operatorname)\{([^{}]*)\}", r"\1", t)
    t = t.replace("\\", "")
    t = t.replace("^", "**")
    t = t.replace("{", "(").replace("}", ")")
    t = _implicit_mul(t)
    try:
        expr = sp.sympify(t, locals={"s": s})
    except Exception as exc:                      # noqa: BLE001
        raise ValueError("无法解析：%s\n-> %s\n(%s)" % (text, t, exc))
    if not expr.free_symbols <= {s}:
        extra = expr.free_symbols - {s}
        raise ValueError("式子里除了 s 还有别的符号：%s" % sorted(map(str, extra)))
    return expr


def to_numden(text):
    """返回 (num, den) numpy 系数数组（降幂）"""
    expr = to_expr(text)
    num, den = sp.fraction(sp.together(expr))
    def coeffs(e):
        p = sp.Poly(sp.expand(e), s)
        vals = []
        for c in p.all_coeffs():
            c = sp.nsimplify(c)
            if c.free_symbols:
                raise ValueError("系数里含符号：%s" % c)
            vals.append(float(c))
        return np.array(vals, float)
    n, d = coeffs(num), coeffs(den)
    if not np.any(np.abs(n) > 0):
        n = np.array([0.0])
    return n, d


# ---------------------------------------------------------------- 频域
def G_of(num, den):
    return lambda w: np.polyval(num, 1j * w) / np.polyval(den, 1j * w)


def bode(num, den, w):
    g = np.polyval(num, 1j * w) / np.polyval(den, 1j * w)
    mag = 20 * np.log10(np.abs(g))
    ph = np.degrees(np.unwrap(np.angle(g)))
    return mag, ph


def crossings(w, y, level=0.0):
    """y - level 的过零点（线性插值）"""
    d = y - level
    out = []
    for i in np.where(np.sign(d[:-1]) * np.sign(d[1:]) < 0)[0]:
        x0, x1 = w[i], w[i + 1]
        y0, y1 = d[i], d[i + 1]
        out.append(x0 + (x1 - x0) * (-y0) / (y1 - y0))
    return np.array(out)


def margins(num, den, w):
    """返回 (ω_c 列表, γ 列表, ω_g 列表, K_g 列表[dB])"""
    mag, ph = bode(num, den, w)
    wc = crossings(w, mag, 0.0)
    gm = []
    for x in wc:
        phx = np.interp(np.log(x), np.log(w), ph)
        gm.append(180 + phx)
    # 相位穿越 -180°−360k
    wg, kg = [], []
    target = -180.0
    while target > ph.min() - 400:
        xs = crossings(w, ph, target)
        for x in xs:
            wg.append(x)
            mg = np.interp(np.log(x), np.log(w), mag)
            kg.append(-mg)
        target -= 360.0
    order = np.argsort(wg)
    wg = np.array(wg)[order]
    kg = np.array(kg)[order]
    return wc, np.array(gm), wg, kg


# ---------------------------------------------------------------- 时域
def _polyadd_same(a, b):
    n = max(len(a), len(b))
    a = np.concatenate([np.zeros(n - len(a)), a])
    b = np.concatenate([np.zeros(n - len(b)), b])
    return a + b


def step_response(num, den, T=None, npts=4001):
    """闭环阶跃响应 y(t)（残数法；重极点退化到 RK4）"""
    cl_num = np.asarray(num, float)
    cl_den = _polyadd_same(np.asarray(den, float), cl_num)
    cl_den = cl_den / cl_den[0]
    cl_num = cl_num / (np.asarray(den, float)[0])

    poles = np.roots(cl_den)
    if poles.size == 0:
        return np.array([0.0]), np.array([cl_den[-1]])

    re = poles.real
    # 原点有极点（含积分/积分串联）：阶跃响应是斜坡或等幅振荡，既不发散也不收敛。
    # 这里不当错误抛出，改用 RK4 给出有限窗口内的真实响应；指标由调用方标为不可用。
    has_origin = bool(np.any(np.abs(poles) < 1e-9))

    if T is None:
        slow = np.min(np.abs(re))
        fast = np.max(np.abs(re))
        if np.any(re > 1e-9):                     # 不稳定：只看一小段
            T = 3.0 / np.max(re[re > 1e-9])
        elif has_origin:                          # 临界：斜坡/等幅振荡，固定窗口
            T = 10.0
        else:
            T = min(12.0 / slow, 400.0 / max(fast, 1e-9))
        T = float(np.clip(T, 1e-4, 5000.0))

    t = np.linspace(0.0, T, npts)

    # 判断有无重极点
    repeated = False
    for i in range(poles.size):
        for j in range(i + 1, poles.size):
            if abs(poles[i] - poles[j]) < 1e-6 * max(1.0, abs(poles[i])):
                repeated = True
    if repeated or has_origin:
        return _step_rk4(cl_num, cl_den, t)

    dD = np.polyder(cl_den)
    y_inf = cl_num[-1] / cl_den[-1] if abs(cl_den[-1]) > 0 else 0.0
    y = np.full(t.size, y_inf, dtype=complex)
    for p in poles:
        r = np.polyval(cl_num, p) / (p * np.polyval(dD, p))
        y += r * np.exp(p * t)
    return t, y.real


def _step_rk4(num, den, t):
    n = den.size - 1
    a = den / den[0]
    b = num / den[0]
    A = np.zeros((n, n))
    A[:n - 1, 1:] = np.eye(n - 1)
    A[-1, :] = -a[1:][::-1]
    B = np.zeros(n)
    B[-1] = 1.0
    C = np.zeros(n)
    for i, c in enumerate(b[::-1]):
        C[i] = c
    x = np.zeros(n)
    y = np.empty(t.size)
    for k, tt in enumerate(t):
        y[k] = C @ x
        if k == t.size - 1:
            break
        dt = t[k + 1] - t[k]
        k1 = A @ x + B
        k2 = A @ (x + dt / 2 * k1) + B
        k3 = A @ (x + dt / 2 * k2) + B
        k4 = A @ (x + dt * k3) + B
        x = x + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return t, y


def time_metrics(t, y, y_inf=None):
    """时域指标。y_inf 不给时取末值；非线性仿真建议给尾部均值。"""
    y_inf = y[-1] if y_inf is None else float(y_inf)
    if abs(y_inf) < 1e-9:
        return dict(sigma=np.nan, tp=np.nan, ts=np.nan, tr=np.nan, y_inf=y_inf)
    peak = y.max()
    tp = t[int(np.argmax(y))]
    sigma = 100.0 * (peak - y_inf) / abs(y_inf)
    band = np.abs(y - y_inf) > 0.02 * abs(y_inf)
    if band.any() and not band[-1]:
        ts = t[np.where(band)[0][-1]]
    elif band.any():
        ts = np.nan          # 到仿真末尾仍在带外 -> 没稳定，不能报"总时长"
    else:
        ts = 0.0
    lo, hi = 0.1 * y_inf, 0.9 * y_inf
    idx = np.where((y >= min(lo, hi)) & (y <= max(lo, hi)))[0]
    tr = (t[idx[0]] if idx.size else np.nan)
    return dict(sigma=sigma, tp=tp, ts=ts, tr=tr, y_inf=y_inf)


def dominant_pair(den):
    """闭环主导共轭极点对 → (ζ, ω_n, p)"""
    p = np.roots(den)
    cand = p[np.abs(p.imag) > 1e-6 * np.maximum(1.0, np.abs(p))]
    if cand.size == 0:
        return None
    i = np.argmin(np.abs(cand.real))
    z = cand[i]
    wn = abs(z)
    return (-z.real / wn, wn, z)


# ---------------------------------------------------------------- 主流程
def analyse(g0_text, gc_text, w=None, label=""):
    n0, d0 = to_numden(g0_text)
    nc, dc = to_numden(gc_text) if gc_text else (np.array([1.0]), np.array([1.0]))
    # 串联：先乘成单个有理函数（sympy 更适合处理高阶乘积）
    e0 = to_expr(g0_text)
    ec = to_expr(gc_text) if gc_text else sp.Integer(1)
    et = sp.cancel(e0 * ec)
    nu, de = sp.fraction(et)
    def coeffs(e):
        p = sp.Poly(sp.expand(e), s)
        return np.array([float(sp.nsimplify(c)) for c in p.all_coeffs()], float)
    num, den = coeffs(nu), coeffs(de)

    if w is None:
        zp = np.roots(den) if len(den) > 1 else np.array([])
        zz = np.roots(num) if len(num) > 1 else np.array([])
        allr = np.concatenate([zp, zz]) if (zp.size or zz.size) else np.array([1.0])
        slow = np.min(np.abs(allr.real[allr.real != 0])) if np.any(allr.real) else 1.0
        fast = np.max(np.abs(allr)) if allr.size else 10.0
        lo = max(1e-3, slow / 1000.0)
        hi = max(1e3, fast * 100.0)
        w = np.logspace(np.log10(lo), np.log10(hi), 30000)

    res = {}
    for tag, (n_, d_) in (("raw", (n0, d0)), ("cmp", (num, den))):
        wc, gm, wg, kg = margins(n_, d_, w)
        res[tag] = dict(num=n_, den=d_, wc=wc, gm=gm, wg=wg, kg=kg,
                        mag=bode(n_, d_, w)[0], ph=bode(n_, d_, w)[1])
    return res, num, den, w


def fmt(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def main():
    ap = argparse.ArgumentParser(description="校正前后一键验算")
    ap.add_argument("-g0", "--g0", required=True, help="原开环传函 G0(s)")
    ap.add_argument("-gc", "--gc", default="", help="校正环节 Gc(s)，省略表示不校正")
    ap.add_argument("-o", "--out", default="ctrl_check.png", help="输出图片")
    ap.add_argument("--title", default="", help="图标题")
    args = ap.parse_args()

    res, num, den, w = analyse(args.g0, args.gc)

    # 闭环
    cl_den = _polyadd_same(den, num)
    t, y = step_response(num, den)
    met = time_metrics(t, y)
    dp = dominant_pair(cl_den)

    # 型别 / 稳态误差（单位阶跃）
    poles_ol = np.roots(den) if len(den) > 1 else np.array([])
    zeros_ol = np.roots(num) if len(num) > 1 else np.array([])
    n_int = int(np.sum(np.abs(poles_ol) < 1e-9))
    kp = np.polyval(num, 0) / np.polyval(den, 0) if abs(np.polyval(den, 0)) > 0 else np.inf
    if n_int >= 1:
        e_ss = 0.0
    else:
        e_ss = 1.0 / (1.0 + kp)

    # ---------------- 图（复用 ctrl_app.draw，与 GUI / 网页完全一致）
    fig = plt.figure(figsize=(11.2, 8.4))
    try:
        import ctrl_app as _ca
        _d = _ca.compute(args.g0, args.gc or "")
        _ca.draw(fig, _d, bool(args.gc), args.gc or "")
        fig.suptitle((args.title or "校正前后对比") + "    "
                     + ("Gc = " + args.gc if args.gc else "（无校正环节）"),
                     fontsize=10.5, y=0.975)
    except Exception:
        traceback.print_exc()
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "绘图失败，见终端", ha="center")
    fig.savefig(args.out, bbox_inches="tight", facecolor="white")

    # ---------------- 打印
    def line(tag, r):
        wc = r["wc"][:1]
        gm = r["gm"][:1]
        ws = ", ".join(f"{x:.4g}" for x in wc) or "无 0dB 交点"
        gs_ = ", ".join(f"{x:.2f}°" for x in gm) or "—"
        return f"  {tag:<10s} ω_c = {ws:<26s} γ = {gs_}"

    has_cmp = bool(args.gc)
    print("\n" + "=" * 74)
    print(" 开环 Bode 指标")
    print("-" * 74)
    print(line("校正前", res["raw"]))
    if has_cmp:
        print(line("校正后", res["cmp"]))
    for tag, cn in (("raw", "校正前"), ("cmp", "校正后")):
        if tag == "cmp" and not has_cmp:
            continue
        r = res[tag]
        if r["wg"].size:
            print(f"  {cn:<10s} ω_g = {', '.join(f'{x:.4g}' for x in r['wg'][:3])}"
                  f"    K_g = {', '.join(fmt(x,2)+' dB' for x in r['kg'][:3])}")
        else:
            print(f"  {cn:<10s} 相位不穿越 -180°，K_g = ∞")
    if has_cmp:
        d_wc = (res["cmp"]["wc"][0] / res["raw"]["wc"][0]) if res["cmp"]["wc"].size and res["raw"]["wc"].size else float("nan")
        d_pm = (res["cmp"]["gm"][0] - res["raw"]["gm"][0]) if res["cmp"]["gm"].size and res["raw"]["gm"].size else float("nan")
        print("-" * 74)
        print(f"  变化        ω_c × {d_wc:.3f}   ({20*np.log10(d_wc):+.2f} dB)"
              f"      γ {d_pm:+.2f}°")

    roots_cl = np.roots(cl_den)
    stable = np.all(roots_cl.real < 1e-9)

    print("\n" + "=" * 74)
    print(" 闭环时域（单位阶跃）")
    print("-" * 74)
    print(f"  稳态误差    e_ss = {e_ss:.5f}  ({(100*e_ss):.2f}%)"
          f"   系统型别 {'0' if n_int==0 else 'I 型及以上'}  K_p = {kp:.6g}")
    if not stable:
        print("  ⚠ 闭环不稳定：阶跃响应发散，σ / t_p / t_s 与阻尼比均无意义")
    else:
        print(f"  稳态值      y(∞) = {met['y_inf']:.5f}")
        print(f"  超调量      σ = {met['sigma']:.2f}%")
        print(f"  峰值时间    t_p = {met['tp']*1000:.1f} ms   ({met['tp']:.4f} s)")
        print(f"  调节时间    t_s(2%) = {met['ts']*1000:.1f} ms   ({met['ts']:.4f} s)")
        if dp:
            z, wn, p = dp
            print(f"  主导极点    {p.real:.4f} ± j{abs(p.imag):.4f}"
                  f"   →  ζ = {z:.3f},  ω_n = {wn:.4f} rad/s")
        else:
            print("  主导极点    无共轭复极点（纯实极点），阻尼比不适用")

    print("\n 开环极点：", ", ".join(f"{v.real:.4g}{v.imag:+.4g}j" if abs(v.imag) > 1e-9
                                else f"{v.real:.4g}" for v in np.sort_complex(poles_ol)))
    if zeros_ol.size:
        print(" 开环零点：", ", ".join(f"{v.real:.4g}{v.imag:+.4g}j" if abs(v.imag) > 1e-9
                                  else f"{v.real:.4g}" for v in np.sort_complex(zeros_ol)))
    print(" 闭环极点：", ", ".join(f"{v.real:.4g}{v.imag:+.4g}j" if abs(v.imag) > 1e-9
                                else f"{v.real:.4g}" for v in np.sort_complex(np.roots(cl_den))))
    stable = np.all(np.roots(cl_den).real < 1e-9)
    print(f"\n 闭环{'稳定' if stable else '不稳定 ⚠'}    （图已存：{os.path.abspath(args.out)}）")
    print("=" * 74 + "\n")


if __name__ == "__main__":
    main()


# ---- 输入预处理：补括号 + 把小写 e 当自然常数 ----
import re as _re


def _prep_expr(t):
    t = _re.sub(r"(?<![A-Za-z0-9_])e(?![A-Za-z0-9_])", "E", t)
    op, cl = t.count("("), t.count(")")
    if op > cl:
        t = t + ")" * (op - cl)
    elif cl > op:
        raise ValueError("括号不配对：左 %d 个、右 %d 个" % (op, cl))
    return t


_orig_imul = _implicit_mul


def _implicit_mul(t, *a, **k):
    return _prep_expr(_orig_imul(t, *a, **k))
