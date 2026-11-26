# -*- coding: utf-8 -*-
"""
离散校正验算器 —— ctrl_check.py 的采样系统版本

    G(z) = ZOH 离散化( G0(s) )，L(z) = D(z)·G(z)，闭环 T(z) = L/(1+L)

支持：
  * G0(s) 用普通表达式或 LaTeX 写
  * 校正环节 D(z) 可以直接写 z 的表达式；也可以写 s 的表达式，按 Tustin/零阶保持离散化
  * 输出：离散 Bode（0 ~ π/T）、ω_c、γ、K_g、阶跃采样、σ、t_p、t_s、闭环极点/稳定性

用法：
    python ctrl_zcheck.py -g0 "10/(s*(s+1))" -T 0.1
    python ctrl_zcheck.py -g0 "10/(s*(s+1))" -gc "(0.5z-0.3)/(z-0.8)" -T 0.1
    python ctrl_zcheck.py -g0 "10/(s*(s+1))" -gc "(s+1)/(s+5)" -T 0.1 --gc-method tustin
"""
import argparse
import re
import sys

import numpy as np
import sympy as sp

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ctrl_check import _convert_frac, _polyadd_same, time_metrics

# Windows 控制台默认 GBK，避免 '−' 之类字符触发 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                              # noqa: BLE001
        pass

z = sp.Symbol("z")
s = sp.Symbol("s")


# ---------------------------------------------------------------- 解析
def _implicit_mul_var(text, v):
    """2s -> 2*s，s( -> s*(，)( -> )*(，2( -> 2*（变量名可指定）"""
    text = re.sub(r"(?<=[0-9])(?=[A-Za-z(])", "*", text)
    text = re.sub(r"(?<=[%s])(?=[%s(0-9])" % (v, v), "*", text)
    text = re.sub(r"(?<=\))(?=[%s(0-9])" % v, "*", text)
    return text


def _parse(text, sym, name="s"):
    """把 LaTeX / 普通表达式解析成 sympy 表达式（自变量 sym）"""
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
    t = _implicit_mul_var(t, name)
    try:
        expr = sp.sympify(t, locals={str(sym): sym})
    except Exception as exc:                       # noqa: BLE001
        raise ValueError("无法解析：%s\n-> %s\n(%s)" % (text, t, exc))
    if not expr.free_symbols <= {sym}:
        extra = expr.free_symbols - {sym}
        raise ValueError("式子里除了 %s 还有别的符号：%s"
                         % (name, sorted(map(str, extra))))
    return expr


def _coeffs(expr, sym):
    p = sp.Poly(sp.expand(sp.numer(sp.together(expr))), sym)
    q = sp.Poly(sp.expand(sp.denom(sp.together(expr))), sym)
    def arr(poly):
        vals = []
        for c in poly.all_coeffs():
            c = sp.nsimplify(c)
            if c.free_symbols:
                raise ValueError("系数里含符号：%s" % c)
            vals.append(float(c))
        return np.array(vals, float)
    return arr(p), arr(q)


def has_var(text, var):
    return re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % var, text) is not None


# ---------------------------------------------------------------- 矩阵指数
def _expm(M):
    """标度-平方 + 泰勒（纯 numpy，够用且稳）"""
    M = np.asarray(M, float)
    n = M.shape[0]
    nrm = np.linalg.norm(M, np.inf)
    k = 0
    while nrm > 0.5:
        nrm /= 2.0
        k += 1
    Ms = M / (2.0 ** k)
    E = np.eye(n)
    term = np.eye(n)
    for i in range(1, 22):
        term = term @ Ms / i
        E = E + term
    for _ in range(k):
        E = E @ E
    return E


# ---------------------------------------------------------------- 连续 → 离散
def tf_to_ss(num, den):
    """可控标准型"""
    num = np.asarray(num, float)
    den = np.asarray(den, float)
    if abs(den[0] - 1.0) > 0:
        num = num / den[0]
        den = den / den[0]
    n = len(den) - 1
    if n == 0:
        return np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0)), np.array([[float(num[0])]])
    # 补足分子长度
    nn = np.concatenate([np.zeros(max(0, n + 1 - len(num))), num])
    d = nn[0]                      # 直通项（b_n）
    c = (nn[1:] - d * den[1:])[::-1]   # 可控标准型的 C（顺序与 A 的伴随行一致）
    A = np.zeros((n, n))
    A[:-1, 1:] = np.eye(n - 1)
    A[-1, :] = -den[:0:-1]         # 末行 = -[a0, a1, ..., a_{n-1}]
    B = np.zeros((n, 1))
    B[-1, 0] = 1.0
    C = np.asarray(c, float).reshape(1, n)
    D = np.array([[d]])
    return A, B, C, D


def zoh_tf(num, den, T):
    """零阶保持离散化：返回 (num_z, den_z)"""
    A, B, C, D = tf_to_ss(num, den)
    n = A.shape[0]
    if n == 0:
        return np.array([float(D[0, 0])]), np.array([1.0])
    # expm([[A, B],[0,0]]·T) 的右上块就是 Bd
    M = np.zeros((n + 1, n + 1))
    M[:n, :n] = A
    M[:n, n:] = B
    E = _expm(M * T)
    Ad = E[:n, :n]
    Bd = E[:n, n:].reshape(n, 1)

    den_z = np.poly(Ad)                       # det(zI - Ad)，首一
    # den_z(z)·C(zI-Ad)^-1·Bd 是 n-1 次多项式，用 n 个点插值
    zk = np.array([2.0 + 1.7 * k for k in range(n)])
    vals = []
    for zz in zk:
        try:
            v = np.linalg.solve(zz * np.eye(n) - Ad, Bd)
        except np.linalg.LinAlgError:
            v = np.linalg.pinv(zz * np.eye(n) - Ad) @ Bd
        vals.append(np.polyval(den_z, zz) * float(np.dot(C[0], v.ravel())))
    if n == 1:
        num_z = np.array([vals[0]], float)
    else:
        num_z = np.polyfit(zk, vals, n - 1)
    num_z = np.asarray(num_z, float)
    pad = len(den_z) - len(num_z)
    if pad > 0:
        num_z = np.concatenate([np.zeros(pad), num_z])
    num_z = num_z + float(D[0, 0]) * den_z
    return _trim(num_z), _trim(den_z)


def tustin_tf(num, den, T):
    """双线性变换 s = 2(z-1)/(T(z+1))，多项式代换"""
    sx = sp.Symbol("s")
    n_expr = sum(float(c) * sx ** (len(num) - 1 - i) for i, c in enumerate(num))
    d_expr = sum(float(c) * sx ** (len(den) - 1 - i) for i, c in enumerate(den))
    sub = 2 * (z - 1) / (T * (z + 1))
    expr = sp.simplify(n_expr.subs(sx, sub) / d_expr.subs(sx, sub))
    n2, d2 = _coeffs(expr, z)
    return _trim(n2 / d2[0]), _trim(d2 / d2[0])


def _trim(a):
    a = np.asarray(a, float)
    nz = np.nonzero(np.abs(a) > 1e-12)[0]
    if nz.size == 0:
        return np.array([0.0])
    return a[nz[0]:]


# ---------------------------------------------------------------- 频域
def zresp(num, den, w, T):
    zz = np.exp(1j * w * T)
    return np.polyval(num, zz) / np.polyval(den, zz)


def zmargins(num, den, T, npts=4000):
    w = np.linspace(1e-6, np.pi / T, npts)
    g = zresp(num, den, w, T)
    mag = 20 * np.log10(np.abs(g))
    ph = np.degrees(np.unwrap(np.angle(g)))
    from ctrl_check import crossings
    wc = crossings(w, mag, 0.0)
    gm = [180 + np.interp(x, w, ph) for x in wc]
    wg, kg = [], []
    target = -180.0
    while target > ph.min() - 400:
        for x in crossings(w, ph, target):
            wg.append(x)
            kg.append(-np.interp(x, w, mag))
        target -= 360.0
    o = np.argsort(wg) if wg else []
    return wc, np.array(gm), (np.array(wg)[o] if len(wg) else np.array([])), \
        (np.array(kg)[o] if len(kg) else np.array([])), w, mag, ph


# ---------------------------------------------------------------- 时域
def zstep(cl_num, cl_den, T, npts=400):
    """差分方程递推（z 域阶跃响应），对重极点也稳"""
    n = np.asarray(cl_num, float).ravel()
    d = np.asarray(cl_den, float).ravel()
    if len(n) < len(d):
        n = np.concatenate([np.zeros(len(d) - len(n)), n])
    d0 = d[0]
    n = n / d0
    d = d / d0
    y = np.zeros(npts)
    for k in range(npts):
        acc = 0.0
        for m in range(len(n)):          # u(k-m) = 1
            if k - m >= 0:
                acc += n[m]
        for m in range(1, len(d)):
            if k - m >= 0:
                acc -= d[m] * y[k - m]
        y[k] = acc
    return np.arange(npts) * T, y


def dominant_z_pair(cl_den):
    """闭环里最“慢”的那对共轭极点（|z| 最大者）"""
    p = np.roots(cl_den)
    p = p[np.abs(p) > 1e-9]
    cand = [q for q in p if abs(q.imag) > 1e-6 and q.imag > 0]
    if not cand:
        return None
    return max(cand, key=abs)


# ---------------------------------------------------------------- 主流程
def analyse(g0_text, gc_text, T, gc_method="tustin"):
    g0_has_z, g0_has_s = has_var(g0_text, "z"), has_var(g0_text, "s")
    gc_has_z, gc_has_s = has_var(gc_text, "z"), has_var(gc_text, "s")

    if gc_has_z and gc_has_s:
        raise ValueError("校正环节里同时出现 s 和 z：离散环节请只写 z，"
                         "连续环节请只写 s（连续环节会自动用 %s 离散化）" % gc_method)

    pure_d = g0_has_z and not g0_has_s        # G0 直接给 z 域 ⇒ 纯离散
    if pure_d:
        if not T or float(T) <= 0:
            raise ValueError("G0 写的是 z 域（纯离散对象），请填采样周期 T")
        n0, d0 = _coeffs(_parse(g0_text, z, "z"), z)
        gz_n, gz_d = _trim(n0), _trim(d0)
        note = "纯离散（G0 已给 z 域，跳过零阶保持）"
    else:
        n0, d0 = _coeffs(_parse(g0_text, s, "s"), s)
        n0, d0 = _trim(n0), _trim(d0)
        gz_n, gz_d = zoh_tf(n0, d0, T)     # 对象 + 零阶保持
        note = "采样系统（G0 连续 + 零阶保持）"

    out = {"T": T, "g_num": gz_n, "g_den": gz_d, "note": note}

    if gc_text.strip():
        if has_var(gc_text, "z"):
            gc_n, gc_d = _coeffs(_parse(gc_text, z, "z"), z)
        else:
            sc_n, sc_d = _coeffs(_parse(gc_text, s, "s"), s)
            if gc_method == "tustin":
                gc_n, gc_d = tustin_tf(sc_n, sc_d, T)
            else:
                gc_n, gc_d = zoh_tf(sc_n, sc_d, T)
        out["gc_num"], out["gc_den"] = _trim(gc_n), _trim(gc_d)
        num = np.polymul(gc_n, gz_n)
        den = np.polymul(gc_d, gz_d)
    else:
        out["gc_num"] = out["gc_den"] = None
        num, den = gz_n, gz_d

    num, den = _trim(num), _trim(den)
    out["num"], out["den"] = num, den

    cl_num, cl_den = num, _trim(_polyadd_same(den, num))
    out["cl_num"], out["cl_den"] = cl_num, cl_den
    roots_cl = np.roots(cl_den)
    out["roots_cl"] = roots_cl
    out["stable"] = bool(np.all(np.abs(roots_cl) < 1.0))
    out["poles_ol"] = np.roots(den)
    out["zeros_ol"] = np.roots(num) if len(num) > 1 else np.array([])

    wc, gm, wg, kg, w, mag, ph = zmargins(num, den, T)
    out.update(wc=wc, gm=gm, wg=wg, kg=kg, w=w, mag=mag, ph=ph)

    t, y = zstep(cl_num, cl_den, T)
    out["t"], out["y"] = t, y
    out["met"] = time_metrics(t, y) if out["stable"] else None
    _d1 = float(np.polyval(cl_den, 1.0))
    out["y_inf"] = (float(np.polyval(cl_num, 1.0)) / _d1) if abs(_d1) > 1e-12 else np.nan

    pmax = dominant_z_pair(cl_den)
    if pmax is not None:
        sdom = np.log(pmax) / T
        wn = abs(sdom)
        zeta = -sdom.real / wn if wn > 0 else np.nan
        out["zeta"], out["wn"], out["zdom"] = zeta, wn, pmax
    else:
        out["zeta"] = out["wn"] = out["zdom"] = None
    return out


def draw(fig, d, has_cmp):
    fig.clear()
    gs = fig.add_gridspec(2, 2, hspace=0.42, wspace=0.30,
                          left=0.08, right=0.96, top=0.88, bottom=0.09)
    A = fig.add_subplot(gs[0, 0])
    B = fig.add_subplot(gs[0, 1])
    C_ = fig.add_subplot(gs[1, 0])
    D = fig.add_subplot(gs[1, 1])

    T = d["T"]
    w = d["w"]
    mag, ph = d["mag"], d["ph"]

    A.plot(w, mag, color="#d1372c", lw=1.6, label="校正后 $L(z)$")
    if has_cmp:
        g = zresp(d["g_num"], d["g_den"], w, T)
        A.plot(w, 20 * np.log10(np.abs(g)), color="#7f8fa6", lw=1.3, ls="--",
               label="校正前 $G(z)$")
    A.axhline(0, color="k", lw=0.8)
    for x in d["wc"]:
        A.axvline(x, color="#d1372c", lw=0.7, ls=":")
        A.plot([x], [0], "o", ms=6, color="#d1372c")
    A.set_xscale("log")
    A.set_xlim(max(1e-3, w[0]), np.pi / T)
    A.set_ylabel("$20\\lg|L|$  (dB)")
    A.set_title("(a) 离散幅频（0 ~ $\\pi/T$）", fontsize=9.5, pad=6)
    A.grid(True, which="both", alpha=0.25, lw=0.5)
    A.legend(fontsize=7.6, loc="best")

    B.plot(w, ph, color="#d1372c", lw=1.6)
    B.axhline(-180, color="0.4", lw=0.8, ls="--")
    B.set_xscale("log")
    B.set_xlim(max(1e-3, w[0]), np.pi / T)
    B.set_ylabel("$\\angle L$  (deg)")
    B.set_title("(b) 离散相频", fontsize=9.5, pad=6)
    B.grid(True, which="both", alpha=0.25, lw=0.5)

    C_.plot(d["t"], d["y"], color="#d1372c", lw=1.4)
    C_.axhline(1, color="k", lw=0.8, ls=":")
    C_.set_xlabel("t = kT  (s)")
    C_.set_ylabel("c(kT)")
    _k = d.get("kind", "step")
    _tn = {"step": "阶跃", "ramp": "斜坡", "accel": "加速度"}.get(_k, "阶跃")
    _tt = "(c) 闭环%s（采样点连线）" % _tn
    if d.get("nl") and d["nl"] != "none":
        _tt += " · 非线性"
    C_.set_title(_tt, fontsize=9.5, pad=6)
    C_.grid(True, alpha=0.25, lw=0.5)

    th = np.linspace(0, 2 * np.pi, 400)
    D.plot(np.cos(th), np.sin(th), color="0.35", lw=1.0, ls="--")
    D.fill_between(np.cos(th), np.sin(th), 1.6, color="0.95", zorder=0)
    po = d["poles_ol"]
    zo = d["zeros_ol"]
    if po.size:
        D.plot(po.real, po.imag, "x", ms=10, mew=2.0, color="#c0392b",
               label="开环极点", zorder=4)
    if zo.size:
        D.plot(zo.real, zo.imag, "o", ms=9, mfc="none", mew=1.8,
               color="#2c8a3e", label="开环零点", zorder=4)
    D.plot(d["roots_cl"].real, d["roots_cl"].imag, "*", ms=13,
           color="#8e44ad", label="闭环极点", zorder=5)
    D.axhline(0, color="k", lw=0.7)
    D.axvline(0, color="k", lw=0.7)
    lim = 1.25 * max(1.05, *(np.abs(np.concatenate([po.ravel(), zo.ravel(),
                                                    d["roots_cl"].ravel()]))))
    D.set_xlim(-lim, lim)
    D.set_ylim(-lim, lim)
    D.set_aspect("equal")
    D.set_xlabel("Re")
    D.set_ylabel("Im")
    D.set_title("(d) z 平面（虚线 = 单位圆）", fontsize=9.5, pad=6)
    D.legend(fontsize=7.6, loc="upper right")
    D.text(-lim * 0.95, lim * 0.80, "单位圆外 = 不稳定", fontsize=7.4,
           color="0.35")
    return fig


def main():
    ap = argparse.ArgumentParser(description="离散校正验算（ZOH 采样）")
    ap.add_argument("-g0", required=True, help="连续对象 G0(s)")
    ap.add_argument("-gc", default="", help="校正环节：可写 z 的 D(z)，也可写 s 的 D(s)")
    ap.add_argument("-T", required=True, type=float, help="采样周期 T (s)")
    ap.add_argument("--gc-method", default="tustin", choices=["tustin", "zoh"],
                    help="若 D 用 s 写，按哪种方法离散化（默认 tustin）")
    ap.add_argument("-o", "--out", default="ctrl_zcheck.png")
    a = ap.parse_args()

    d = analyse(a.g0, a.gc, a.T, a.gc_method)
    T = d["T"]

    print("=" * 74)
    print("  采样系统（T = %g s，零阶保持）" % T)
    print("-" * 74)
    print("  G(z) 分子：", np.array2string(d["g_num"], precision=5))
    print("  G(z) 分母：", np.array2string(d["g_den"], precision=5))
    if d["gc_num"] is not None:
        print("  D(z) 分子：", np.array2string(d["gc_num"], precision=5))
        print("  D(z) 分母：", np.array2string(d["gc_den"], precision=5))
    print("-" * 74)
    if d["wc"].size:
        for x, g in zip(d["wc"], d["gm"]):
            print("  ω_c = %-10.4f γ = %.2f°" % (x, g))
    else:
        print("  幅频不穿越 0 dB（无 ω_c）")
    if d["wg"].size:
        for x, g in zip(d["wg"], d["kg"]):
            print("  ω_g = %-10.4f K_g = %.2f dB" % (x, g))
    else:
        print("  相位不穿越 -180°，K_g = ∞")
    print("-" * 74)
    if d["stable"]:
        m = d["met"]
        print("  稳态值 y(∞) = %.5f" % d["y_inf"])
        if m:
            print("  超调量 σ = %.2f%%   峰值 t_p = %.1f ms   t_s(2%%) = %.1f ms"
                  % (m["sigma"], m["tp"] * 1e3, m["ts"] * 1e3))
        if d["zeta"] is not None:
            print("  主导极点 z = %.4f%+.4fj  →  ζ = %.3f, ω_n = %.3f rad/s"
                  % (d["zdom"].real, d["zdom"].imag, d["zeta"], d["wn"]))
        print("  闭环稳定 ✔")
    else:
        print("  ⚠ 闭环不稳定：有 |z| > 1 的闭环极点，阶跃响应发散")
        print("    |z| 最大 = %.4f" % np.max(np.abs(d["roots_cl"])))
    print("  开环极点：", np.array2string(d["poles_ol"], precision=4))
    print("  闭环极点：", np.array2string(d["roots_cl"], precision=4))
    print("=" * 74)

    fig = plt.figure(figsize=(11.0, 7.4))
    fig.suptitle("离散系统：$G_0(s)$ = %s，T = %g s%s"
                 % (a.g0, T, ("，D = %s" % a.gc) if a.gc else ""),
                 fontsize=10.5, y=0.97)
    draw(fig, d, bool(a.gc.strip()))
    fig.savefig(a.out, dpi=150, bbox_inches="tight", facecolor="white")
    print("图已保存：", a.out)


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


_orig_imul = _implicit_mul_var


def _implicit_mul_var(t, *a, **k):
    return _prep_expr(_orig_imul(t, *a, **k))
