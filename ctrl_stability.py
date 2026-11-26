# -*- coding: utf-8 -*-
"""
ctrl_stability.py —— 稳定性判据可视化内核

连续系统：Routh 判据（首列符号变化）、Nyquist 判据（包围圈数 N、Z=N+P）、
          对数稳定判据（相位穿越 + 裕度）、描述函数法（自振点）、相轨迹
离散系统：Jury 判据（Jury 表 + 全部条件）、单位圆判据（|z|<1）

对外接口：
    analyse(num, den, discrete=False, T=None, kind="relay", amp_max=20)
        -> dict，含各判据的结论 + 画图数据
    draw(fig, d)   # 4 联图
"""

from __future__ import annotations

import numpy as np

import matplotlib

from fractions import Fraction


# ---------------------------------------------------------------- 多项式小工具
def _trim(p, tol=1e-12):
    a = np.asarray(p, dtype=float).ravel()
    i = 0
    while i < a.size - 1 and abs(a[i]) < tol:
        i += 1
    return a[i:]


def _peval(p, s):
    """Horner，支持复数 s 数组"""
    out = np.zeros_like(s, dtype=complex)
    for c in p:
        out = out * s + c
    return out


def _r2frac(x, lim=10 ** 9):
    f = Fraction(float(x)).limit_denominator(lim)
    return f


# ---------------------------------------------------------------- Routh
def routh(den):
    """Routh 表。返回 dict：table / col / changes / stable / note"""
    a = _trim(np.asarray(den, dtype=float))
    n = a.size - 1
    if n <= 0:
        return dict(table=[], col=[], changes=0, stable=True, note="零阶，恒稳定")
    coef = [_r2frac(c) for c in a]

    rows = n + 1
    tab = [[Fraction(0)] * (n + 1) for _ in range(rows)]
    for i, c in enumerate(coef):
        tab[i % 2][i // 2] = c      # 第 0 行放 a_n, a_{n-2}, ...；第 1 行放 a_{n-1}, ...

    def fill(m):
        for j in range(n - m + 1):
            if tab[m - 1][0] == 0:
                tab[m - 1][0] = Fraction(1, 10 ** 6)   # 补 ε
            num = (tab[m - 1][0] * tab[m - 2][j + 1]
                   - tab[m - 2][0] * tab[m - 1][j + 1])
            tab[m][j] = num / tab[m - 1][0]

    note = ""
    for m in range(2, rows):
        if all(v == 0 for v in tab[m - 1]):
            # 全零行：用上一行构造辅助多项式再求导
            aux = [tab[m - 2][j] * Fraction(max(n - m + 2, 1)) for j in range(n + 1)]
            tab[m - 1] = aux
            note = "出现全零行，已用辅助多项式求导替代"
        fill(m)

    col = [tab[i][0] for i in range(rows)]
    signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in col]
    changes = sum(1 for i in range(len(signs) - 1)
                  if signs[i] and signs[i + 1] and signs[i] != signs[i + 1])
    # 首列出现零时，只看变号数会漏掉「根压在虚轴/原点」的情形。
    # 用根的位置兜底，把「真在左半平面」与「临界稳定」分开。
    try:
        rt = np.roots(a)
    except Exception:
        rt = np.array([])
    has_rhp = bool(np.any(rt.real > 1e-9))
    has_axis = bool(np.any(np.abs(rt.real) <= 1e-9))
    marginal = (not has_rhp) and has_axis
    if marginal and not note:
        note = "首列出现零：有根落在虚轴/原点，属临界稳定"
    return dict(table=tab, col=col, changes=changes, roots=rt,
                has_rhp=has_rhp, marginal=marginal,
                stable=(changes == 0 and not marginal),
                note=note, order=n)


# ---------------------------------------------------------------- Nyquist
def nyquist_encirclements(num, den, R=1e4, npts=4000):
    """
    沿"右半平面边界"（虚轴 + 右侧大半圆 + 原点小半圆）走一圈，
    数 1+G 绕原点的圈数 N（逆时针为正），再给 Z = N + P。
    """
    n = np.asarray(num, dtype=float)
    d = np.asarray(den, dtype=float)
    # 开环右半平面极点数
    P = int(np.sum(np.roots(d).real > 0))
    # 原点处极点重数（分母前导零个数）
    dz = np.trim_zeros(d, "b")
    nu = int(d.size - dz.size)   # 原点极点个数（不改变 d 本身）

    eps = 1e-3
    seg = []
    # 1) 原点小半圆：s = eps*e^{jθ}, θ: -π/2 → +π/2（绕过右侧）
    th = np.linspace(-np.pi / 2, np.pi / 2, 400)
    seg.append(eps * np.exp(1j * th))
    # 2) 正虚轴：s = jω, ω: eps → R
    w = np.logspace(np.log10(eps), np.log10(R), npts // 2)
    seg.append(1j * w)
    # 3) 右侧大半圆：s = R e^{jθ}, θ: π/2 → -π/2
    th2 = np.linspace(np.pi / 2, -np.pi / 2, 400)
    seg.append(R * np.exp(1j * th2))
    # 4) 负虚轴：s = jω, ω: -R → -eps
    seg.append(1j * (-w[::-1]))

    S = np.concatenate(seg)
    F = 1.0 + _peval(n, S) / _peval(d, S)
    ang = np.unwrap(np.angle(F))
    n_raw = (ang[-1] - ang[0]) / (2 * np.pi)
    # 本实现沿右半平面边界"顺时针"走，故顺时针包围数 N = -n_raw
    N = int(round(-n_raw))
    Z = P + N                      # Z = P + N（N 为顺时针圈数）
    # 曲线正好穿过 (-1,j0) 时，圈数取整会给出 Z=0 的假象；
    # 用闭环特征根兜底：有根落在虚轴/原点 -> 临界稳定。
    ch = d.copy()
    ch[-n.size:] += n
    try:
        crt = np.roots(ch)
    except Exception:
        crt = np.array([])
    has_rhp = bool(np.any(crt.real > 1e-9))
    marginal = (not has_rhp) and bool(np.any(np.abs(crt.real) <= 1e-9))
    return dict(N=N, P=P, Z=Z, nu=nu, marginal=marginal, roots=crt,
                stable=(Z == 0 and not marginal))


def nyquist_curve(num, den, npts=2000):
    n = np.asarray(num, dtype=float)
    d = np.asarray(den, dtype=float)
    w = np.logspace(-3, 4, npts)
    G = _peval(n, 1j * w) / _peval(d, 1j * w)
    return w, G


# ---------------------------------------------------------------- Bode 判据
def bode_phase_cross(num, den, npts=20000):
    """相位穿越频率 + 幅值裕度（对数稳定判据用）"""
    n = np.asarray(num, dtype=float)
    d = np.asarray(den, dtype=float)
    w = np.logspace(-3, 4, npts)
    G = _peval(n, 1j * w) / _peval(d, 1j * w)
    ph = np.unwrap(np.angle(G))
    phd = np.degrees(ph)
    L = 20 * np.log10(np.abs(G) + 1e-300)

    # 0 dB 穿越
    cross = np.where(np.diff(np.sign(L)) != 0)[0]
    wc = [float(w[i] * (w[i + 1] / w[i]) ** (abs(L[i]) / (abs(L[i]) + abs(L[i + 1]))))
          for i in cross[:5]]
    # -180-360k 穿越
    wg, Lg = [], []
    for k in range(-3, 2):
        target = -180.0 + 360.0 * k
        idx = np.where(np.diff(np.sign(phd - target)) != 0)[0]
        for i in idx[:4]:
            wg.append(float(w[i]))
            Lg.append(float(L[i]))
    return dict(w=w, L=L, mag=np.abs(G), ph=phd, wc=wc, wg=wg, Lg=Lg)


# ---------------------------------------------------------------- Jury
def jury(den):
    """
    Jury 判据：D(z) = a_n z^n + ... + a_0
      必要条件  |a_0| < |a_n|
      充分条件  D(1) > 0, (-1)^n D(-1) > 0,
                以及逐行 |b_0| > |b_{n-1}|, |c_0| > |c_{n-2}|, ...
    """
    a = _trim(np.asarray(den, dtype=float))
    if a.size < 2:
        return dict(rows=[], conds=[], stable=True, order=0)
    if a[0] < 0:
        a = -a
    n = a.size - 1
    co = list(a[::-1])                      # 升幂：a0, a1, ..., an

    rows = [co[:]]
    conds = []

    def fmt(x):
        return "%.4g" % x

    conds.append(("|a0| < |an|",
                  abs(co[0]) < abs(co[-1]),
                  "|%s| < |%s|" % (fmt(co[0]), fmt(co[-1]))))

    v1 = float(np.polyval(a, 1.0))
    conds.append(("D(1) > 0", v1 > 0, "D(1) = %s" % fmt(v1)))

    vm = float(np.polyval(a, -1.0)) * ((-1) ** n)
    conds.append(("(-1)^n*D(-1) > 0", vm > 0,
                  "(-1)^%d*D(-1) = %s" % (n, fmt(vm))))

    cur = co
    for k in range(n - 1):
        m = len(cur) - 1
        if m < 1:
            break
        b = [cur[0] * cur[i] - cur[m] * cur[m - i] for i in range(m)]
        rows.append(b[:])
        conds.append(("|%s0| > |%s%d|" % ("bcdefgh"[k], "bcdefgh"[k], m - 1),
                      abs(b[0]) > abs(b[-1]),
                      "|%s| vs |%s|" % (fmt(b[0]), fmt(b[-1]))))
        cur = b

    return dict(rows=rows, conds=conds, stable=all(c[1] for c in conds), order=n)


def unit_circle(den):
    z = np.roots(np.asarray(den, dtype=float))
    r = float(np.max(np.abs(z))) if z.size else 0.0
    marginal = abs(r - 1.0) < 1e-6
    return dict(roots=z, rmax=r, marginal=marginal,
                stable=(r < 1.0 and not marginal))


# ---------------------------------------------------------------- 描述函数
def df_gain(kind, A, M=1.0, a=1.0):
    """非线性环节的描述函数 N(A)（基波增益）。

    滞环继电器（开关阈值 ±a）的 N(A) 是复值：
        N(A) = 4M/(πA)·[√(1−(a/A)²) − j·(a/A)] ，A > a
    """
    A = np.maximum(np.asarray(A, float), 1e-9)
    if kind == "relay":                       # 理想继电器 N=4M/(pi A)
        return 4.0 * M / (np.pi * A)
    if kind == "relay_dz":                    # 带死区继电器
        r = np.clip(a / A, 0.0, 0.999999)
        N = 4.0 * M / (np.pi * A) * np.sqrt(1.0 - r ** 2)
        return np.where(A > a, N, 0.0)
    if kind == "relay_hyst":                  # 滞环继电器（复值）
        r = np.clip(a / A, 0.0, 1.0)
        q = np.sqrt(np.maximum(0.0, 1.0 - r ** 2))
        N = 4.0 * M / (np.pi * A) * (q - 1j * r)
        return np.where(A > a, N, 0.0 + 0.0j)
    # 饱和：斜率 1、线性区半宽 a（=饱和值）；A<=a 时 N=1
    r = np.clip(a / A, 0.0, 1.0)
    N = 2.0 / np.pi * (np.arcsin(r) + r * np.sqrt(np.maximum(0.0, 1.0 - r ** 2)))
    N = np.where(A >= a, N, 1.0)
    return np.maximum(N, 1e-12)


def neg_inv_df(kind, A, M=1.0, a=1.0):
    """返回 −1/N(A)。参数：M=继电器输出幅值；a=死区半宽 / 线性区半宽 / 滞环半宽"""
    N = df_gain(kind, A, M, a)
    if np.iscomplexobj(N):
        mag = np.abs(N)
        safe = np.where(mag > 1e-12, N, 1e-12 + 0j)
        return -1.0 / safe
    with np.errstate(divide="ignore", invalid="ignore"):
        return -1.0 / np.where(N > 1e-12, N, 1e-12)



def _df_curve(num, den, discrete=False, T=None, npts=20000):
    """G(jω)（连续）或 G(e^{jωT})（离散）的密集频率曲线。"""
    n = np.asarray(num, float)
    d = np.asarray(den, float)
    if discrete:
        wmax = np.pi / max(float(T or 1.0), 1e-9) * 0.999
        w = np.logspace(-3, np.log10(max(wmax, 1e-3)), npts)
        z = np.exp(1j * w * max(float(T or 1.0), 1e-9))
        G = _peval(n, z) / _peval(d, z)
    else:
        w = np.logspace(-3, 4.0, npts)
        G = _peval(n, 1j * w) / _peval(d, 1j * w)
    return w, G


def _neg_real_crossings(w, G):
    """找 G 曲线穿过负实轴的频率与实部值（线性插值）。"""
    re, im = G.real, G.imag
    out = []
    for i in range(len(w) - 1):
        if not (np.isfinite(re[i]) and np.isfinite(re[i + 1])):
            continue
        if re[i] >= 0 or re[i + 1] >= 0:
            continue
        if im[i] == 0.0:
            out.append((float(w[i]), float(re[i])))
            continue
        if im[i] * im[i + 1] > 0:
            continue
        t = im[i] / (im[i] - im[i + 1])
        lw = np.log(w[i]) + t * (np.log(w[i + 1]) - np.log(w[i]))
        rc = re[i] + t * (re[i + 1] - re[i])
        if rc < 0:
            out.append((float(np.exp(lw)), float(rc)))
    # 去掉重复交点（数值上相邻两点）
    uniq = []
    for wc, rc in out:
        if uniq and abs(np.log(wc / uniq[-1][0])) < 1e-3:
            continue
        uniq.append((wc, rc))
    return uniq


def _bisect(f, lo, hi, it=90):
    flo, fhi = f(lo), f(hi)
    if not (np.isfinite(flo) and np.isfinite(fhi)) or flo * fhi > 0:
        return None
    for _ in range(it):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if not np.isfinite(fm):
            return None
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def _solve_amp(kind, rc, M, a):
    """解 −1/N(A)=rc（rc<0），返回所有 A>0 的解。"""
    if not (rc < 0):
        return []
    if kind == "relay":
        return [max(1e-6, -4.0 * M * rc / np.pi)]
    if kind == "sat":
        target = -rc
        if target < 1.0:
            return []
        f = lambda A: float(neg_inv_df("sat", np.array([A]), M, a)[0]) - rc
        lo = max(a * (1.0 + 1e-9), 1e-9)
        hi = max(2.0 * a, 1.0)
        for _ in range(60):
            if f(hi) <= 0:
                break
            hi *= 2.0
        else:
            return []
        root = _bisect(f, lo, hi)
        return [root] if root else []
    # 带死区继电器：最小值 |−1/N| = pi*a/(2M)（A=sqrt(2)a）
    target = -rc
    mn = np.pi * a / (2.0 * M)
    if target < mn * (1.0 - 1e-9):
        return []
    if abs(target - mn) <= 1e-6 * max(1.0, mn):
        return [np.sqrt(2.0) * a]
    f = lambda A: float(neg_inv_df("relay_dz", np.array([A]), M, a)[0]) - rc
    # 在对数刻度上扫描，找两个根（A→a+ 与 A→∞ 各一次）
    us = np.logspace(np.log10(1.0 + 1e-7), 6.0, 4000)
    vals = [f(u * a) for u in us]
    roots = []
    for i in range(len(us) - 1):
        if np.isfinite(vals[i]) and np.isfinite(vals[i + 1]) and vals[i] * vals[i + 1] < 0:
            rt = _bisect(f, us[i] * a, us[i + 1] * a)
            if rt and all(abs(rt - q) > 1e-6 * max(1.0, rt) for q in roots):
                roots.append(rt)
    return roots


def _level_crossings(w, G, level):
    """找 G 曲线穿过水平线 Im = level 的频率与实部（对数频率上线性插值）。"""
    re, im = G.real, G.imag
    out = []
    for i in range(len(w) - 1):
        d0, d1 = im[i] - level, im[i + 1] - level
        if not (np.isfinite(d0) and np.isfinite(d1)
                and np.isfinite(re[i]) and np.isfinite(re[i + 1])):
            continue
        if d0 * d1 > 0 or d0 == d1:
            continue
        t = d0 / (d0 - d1)
        rc = re[i] + t * (re[i + 1] - re[i])
        if not (rc < 0):
            continue
        lw = np.log(w[i]) + t * (np.log(w[i + 1]) - np.log(w[i]))
        out.append((float(np.exp(lw)), float(rc)))
    uniq = []
    for wc, rc in out:
        if uniq and abs(np.log(wc / uniq[-1][0])) < 1e-3:
            continue
        uniq.append((wc, rc))
    return uniq


def _limit_cycle_stability(num, den, A, w, M, a, cycles=10, per=100):
    """用零输入自由响应判断自振点稳定与否（连续系统）。

    步长同时受「每周期采样数」与「最快闭环极点」限制，避免长周期自振
    因步长过大而数值发散；算不动时返回 stable=None（不下结论）。
    """
    if not (np.isfinite(A) and A > 0 and np.isfinite(w) and w > 0):
        return dict(stable=None, amp=None)
    try:
        from ctrl_nonlinear import free_response
    except Exception:
        return dict(stable=None, amp=None)
    per_t = 2.0 * np.pi / w
    try:
        rts = np.roots(np.asarray(den, float))
        wfast = float(np.max(np.abs(rts))) if rts.size else 1.0
    except Exception:
        wfast = 1.0
    dt_need = min(per_t / per, 0.1 / max(wfast, 1e-6))
    T_end = per_t * cycles
    npts = int(np.ceil(T_end / dt_need))
    if npts > 45000 or npts < 200:
        return dict(stable=None, amp=None)
    t, y = free_response(num, den, T_end, npts,
                         nl="relay_hyst", M=M, a=a, y0=0.8 * A)
    if y is None or y.size < 20 or not np.all(np.isfinite(y)):
        return dict(stable=None, amp=None)
    idx = np.linspace(0, y.size - 1, cycles + 1).astype(int)
    amps = [float(np.max(np.abs(y[idx[i]:idx[i + 1] + 1]))) for i in range(cycles)]
    amps = [v for v in amps if np.isfinite(v)]
    if len(amps) < 6:
        return dict(stable=None, amp=None)
    half = len(amps) // 2
    a_prev = float(np.mean(amps[half // 2:half]))
    a_last = float(np.mean(amps[-max(3, half // 2):]))
    grow = (a_last - a_prev) / max(a_last, a_prev, 1e-12)
    if a_last > 25.0 * A or a_last > 25.0 * max(a, 1e-9):
        return dict(stable=False, amp=a_last)          # 发散
    if a_last < 0.05 * A:
        return dict(stable=False, amp=a_last)          # 衰减到零
    ok_amp = 0.4 * A <= a_last <= 2.5 * A
    stable = bool(ok_amp and abs(grow) < 0.08)
    return dict(stable=stable, amp=a_last)


def describing_function(num, den, kind="sat", amp_max=20.0, npts=400,
                        M=1.0, a=1.0, discrete=False, T=None,
                        check_stability=False):
    """找 −1/N(A) 与 G(jω) 的交点，给出自振幅值 A、频率 ω 与周期。

    理想继电器 / 带死区继电器 / 饱和：−1/N(A) 落在负实轴上，交点是 G(jω)
    的负实轴穿越点，再按各类 N(A) 反解 A。
    滞环继电器：−1/N(A) = −(π/4M)(√(A²−a²) + j·a) 是一条 Im = −πa/(4M)
    的水平射线（A 增大朝 −∞ 延伸），交点是 G(jω) 与这条水平线的交点。
    """
    A = np.linspace(0.02, amp_max, npts)
    ni = neg_inv_df(kind, A, M, a)
    w, G = _df_curve(num, den, discrete=discrete, T=T)
    cycles = []
    if kind == "relay_hyst":
        level = -np.pi * a / (4.0 * M)
        for wc, rc in _level_crossings(w, G, level):
            amp = float(np.sqrt(a * a + (4.0 * M * abs(rc) / np.pi) ** 2))
            if not np.isfinite(amp) or amp <= a:
                continue
            N = complex(df_gain(kind, np.array([amp]), M, a)[0])
            cycles.append(dict(A=amp, w=float(wc), N=N,
                               G=complex(rc, level),
                               period=float(2.0 * np.pi / wc) if wc > 0 else None,
                               stable=None, amp_sim=None))
    else:
        for wc, rc in _neg_real_crossings(w, G):
            for amp in _solve_amp(kind, rc, M, a):
                N = float(df_gain(kind, np.array([amp]), M, a)[0])
                cycles.append(dict(A=float(amp), w=float(wc), N=N,
                                   G=complex(rc, 0.0),
                                   period=float(2.0 * np.pi / wc) if wc > 0 else None,
                                   stable=None, amp_sim=None))
    cycles.sort(key=lambda c: c["A"])
    if check_stability and kind == "relay_hyst" and not discrete:
        for c in cycles:
            v = _limit_cycle_stability(num, den, c["A"], c["w"], M, a)
            c["stable"] = v["stable"]
            c["amp_sim"] = v["amp"]
    hits = [[c["A"], c["G"].real, c["G"].imag] for c in cycles]
    return dict(A=A, ni=ni, hits=hits, cycles=cycles, w=w, G=G,
                kind=kind, M=M, a=a)



# ---------------------------------------------------------------- 相轨迹
def phase_portrait(A, xlim=(-3, 3), ylim=(-3, 3), n=13, tmax=12.0):
    """二阶系统 ẋ = A x 的相图（数值积分）。

    所有初值一起推（RK4 向量化），比逐条 Python 循环快两个数量级：
    13x13 网格、600 步从 ~4.4 s 降到 ~20 ms。
    """
    A = np.asarray(A, dtype=float)
    AT = A.T
    dt = 0.02
    steps = int(round(tmax / dt))

    xs = np.linspace(xlim[0], xlim[1], n)
    ys = np.linspace(ylim[0], ylim[1], n)
    P0 = np.array([[x, y] for x in xs for y in ys
                   if not (abs(x) < 1e-9 and abs(y) < 1e-9)], dtype=float)
    m = P0.shape[0]
    if m == 0:
        return []

    hist = np.full((steps + 1, m, 2), np.nan)
    hist[0] = P0
    P = P0.copy()
    alive = np.ones(m, dtype=bool)
    for k in range(steps):
        k1 = P @ AT
        k2 = (P + 0.5 * dt * k1) @ AT
        k3 = (P + 0.5 * dt * k2) @ AT
        k4 = (P + dt * k3) @ AT
        P = P + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        bad = (~np.isfinite(P).all(axis=1)) | (np.hypot(P[:, 0], P[:, 1]) > 50)
        if bad.any():
            P[bad] = np.nan
            alive &= ~bad
        hist[k + 1] = P
        if not alive.any():
            break

    traj = []
    for i in range(m):
        tr = hist[:, i, :]
        ok = np.isfinite(tr[:, 0])
        if not ok[0]:
            continue
        # 只取从起点开始连续的一段
        cut = np.argmin(ok) if not ok.all() else ok.size
        if cut >= 2:
            traj.append(tr[:cut])
    return traj


# ---------------------------------------------------------------- 总入口
def analyse(num, den, discrete=False, T=None, kind="sat", amp_max=20.0,
            ch=None, M=1.0, a=1.0):
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    r = dict(discrete=discrete, T=T, kind=kind, num=num, den=den,
             stable=None)

    if ch is None:
        ch = den.astype(float).copy()
        ch[-len(num):] += num        # 闭环特征多项式 den + num
    else:
        ch = np.asarray(ch, dtype=float)
    r["ch"] = ch

    if not discrete:
        r["routh"] = routh(ch)
        r["nyq"] = nyquist_encirclements(num, den)
        r["bode"] = bode_phase_cross(num, den)
        try:
            r["df"] = describing_function(num, den, kind, amp_max, M=M, a=a,
                                          discrete=discrete, T=T,
                                          check_stability=True)
        except Exception:
            r["df"] = None
        # 闭环 A 阵（可控标准型 → 相图）
        if len(den) - 1 == 2:
            cl = den.astype(float).copy()
            cl[-len(num):] += num
            if cl[0] != 0:
                cl = cl / cl[0]
            a1, a2 = cl[1], cl[2]
            A = np.array([[0.0, 1.0], [-a2, -a1]])
            r["portrait"] = dict(A=A, traj=phase_portrait(A))
    else:
        r["jury"] = jury(ch)          # 离散必须用闭环特征式
        r["uc"] = unit_circle(ch)
        try:
            r["df"] = describing_function(num, den, kind, amp_max, M=M, a=a,
                                          discrete=True, T=T)
        except Exception:
            r["df"] = None

    if discrete:
        r["stable"] = bool(r["jury"]["stable"] and r["uc"]["stable"])
        mg = bool(r["uc"].get("marginal")) or bool(r["jury"].get("marginal"))
        r["marginal"] = bool(mg)
        if mg:
            r["stable"] = False
    else:
        mg = bool(r["routh"].get("marginal")) or bool(r["nyq"].get("marginal"))
        r["marginal"] = bool(mg)
        r["stable"] = bool(r["nyq"]["stable"]) and not mg
    return r


# ---------------------------------------------------------------- 绘图
def _frac_str(fr):
    try:
        f = fr.limit_denominator(1000)
        if f.denominator == 1:
            return str(f.numerator)
        return "%d/%d" % (f.numerator, f.denominator)
    except Exception:
        return "%.3f" % float(fr)


def draw(fig, d, zoom=1.0):
    """稳定性可视化 2x2：判据表 / Nyquist 或单位圆 / Bode / 非线性"""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    fig.clear()
    gs = fig.add_gridspec(2, 2, hspace=0.38, wspace=0.28,
                          left=0.07, right=0.97, top=0.88, bottom=0.09)
    axs = [fig.add_subplot(gs[i // 2, i % 2]) for i in range(4)]
    discrete = d.get("discrete", False)
    ink = "#243447"
    good, bad, warn = "#12805c", "#c0392b", "#b45309"

    # ---------------- (a) 判据表
    A = axs[0]
    A.axis("off")
    if not discrete:
        r = d["routh"]
        rows = r["table"]
        nrow = len(rows)
        ncol = max(len(x) for x in rows)
        A.set_title("Routh 表：闭环特征式，首列 %d 次变号 -> %d 个右半平面根"
                    % (r["changes"], r["changes"]), fontsize=9.5, color=ink)
        ys = 1.0 - 0.06
        for i, row in enumerate(rows):
            y = ys - i * (0.86 / max(1, nrow))
            lab = "s^%d" % (nrow - 1 - i)
            A.text(0.02, y, lab, fontsize=8.5, color="0.45", va="center")
            for j, v in enumerate(row):
                if j >= ncol:
                    break
                txt = _frac_str(v)
                col = ink
                if j == 0:
                    col = good if float(v) > 0 else (bad if float(v) < 0 else "0.4")
                A.text(0.16 + j * (0.30 if ncol <= 4 else 0.21), y, txt,
                       fontsize=8.2, color=col, va="center",
                       fontweight="bold" if j == 0 else "normal")
        A.set_xlim(0, 1)
        A.set_ylim(-0.02, 1.02)
        verdict = ("首列出现零，无右半平面根 -> 闭环临界稳定"
                   if r.get("marginal") else
                   ("首列无变号 -> 闭环稳定" if r["stable"] else
                    "首列 %d 次变号 -> 闭环不稳定" % r["changes"]))
        A.text(0.02, 0.02, verdict, fontsize=9,
               color=warn if r.get("marginal") else (good if r["stable"] else bad),
               fontweight="bold")
    else:
        jr = d["jury"]
        n = jr["order"]
        A.set_title("Jury 判据（D(z) 的 %d 阶）" % n, fontsize=9.5, color=ink)
        y = 0.92
        for name, ok, info in jr["conds"]:
            A.text(0.03, y, ("[OK] " if ok else "[X] ") + name, fontsize=8.4,
                   color=good if ok else bad, va="center")
            A.text(0.52, y, info, fontsize=7.8, color="0.35", va="center")
            y -= 0.11
        A.text(0.03, max(0.02, y - 0.02),
               "全部满足 -> 闭环稳定" if jr["stable"] else "存在不满足 -> 闭环不稳定",
               fontsize=9, color=good if jr["stable"] else bad, fontweight="bold")
        A.set_xlim(0, 1)
        A.set_ylim(0, 1)

    # ---------------- (b) Nyquist / 单位圆
    B = axs[1]
    if not discrete:
        nyq = d["nyq"]
        w, G = nyquist_curve(d["num"], d["den"], 1500)
        B.plot(G.real, G.imag, color="#1f6fb4", lw=1.3, label="G(jω), ω>0")
        # 沿 ω 增大方向标 3 个箭头
        for _fr in (0.96,):
            _j = int(np.clip(round(_fr * (len(G) - 2)), 1, len(G) - 2))
            B.annotate("", xy=(G[_j - 1].real, G[_j - 1].imag),
                       xytext=(G[_j + 1].real, G[_j + 1].imag),
                       arrowprops=dict(arrowstyle="-|>", color="#1f6fb4",
                                       lw=1.0, shrinkA=0, shrinkB=0))
        B.plot(G.real, -G.imag, color="#1f6fb4", lw=0.9, alpha=0.35,
               label="镜像 ω<0")
        df = d.get("df")
        if df is not None:
            ni = np.asarray(df["ni"])
            if np.iscomplexobj(ni):
                ok = (np.isfinite(ni.real) & np.isfinite(ni.imag)
                      & (np.abs(ni) < 60))
                B.plot(ni.real[ok], ni.imag[ok], "--", color="#e07b39",
                       lw=1.2, label="$-$1/N(A)")
            else:
                ni = np.asarray(ni, float)
                ok = np.isfinite(ni) & (np.abs(ni) < 60)
                B.plot(ni[ok], np.zeros(int(np.sum(ok))), "--", color="#e07b39",
                       lw=1.2, label="$-$1/N(A)")
            cycles = df.get("cycles") or []
            groups = {}
            for c in cycles[:6]:
                key = (round(float(c["G"].real), 6), round(float(c["G"].imag), 6))
                groups.setdefault(key, []).append(c)
            for k, ((xr, yi), cs) in enumerate(sorted(groups.items())):
                B.plot([xr], [yi], "o", ms=6, mfc="#e07b39", mec="white",
                       mew=1.0, zorder=5)
                amps = "/".join("%.3g" % c["A"] for c in cs)
                ws = "/".join("%.3g" % c["w"] for c in cs)
                lab = "A=%s\nω=%s" % (amps, ws)
                if cs[0].get("stable") is not None:
                    lab += "\n" + ("稳定自振" if cs[0]["stable"] else "不稳定自振")
                B.annotate(lab, xy=(xr, yi), xytext=(-8, 12 + 30 * k),
                           textcoords="offset points", fontsize=7,
                           color="#e07b39", ha="right")
        B.plot([-1], [0], "o", ms=9, mfc="#d1372c", mec="white", mew=1.4,
               zorder=6)
        B.annotate("$(-1,j0)$", xy=(-1, 0), xytext=(8, 10),
                   textcoords="offset points", fontsize=8, color="#d1372c")
        B.axhline(0, color="k", lw=0.6)
        B.axvline(0, color="k", lw=0.6)
        B.set_title("Nyquist：N=%d, P=%d -> Z=P+N=%d%s"
                    % (nyq["N"], nyq["P"], nyq["Z"],
                       "（临界：过 (−1,j0)）" if nyq.get("marginal") else ""),
                    fontsize=9.5, color=warn if nyq.get("marginal") else ink)
        # 视野：以 |G|≈1 的穿越区为中心，避免远场把画面压扁
        gi = int(np.argmin(np.abs(np.abs(G) - 1.0)))
        base = max(2.0, 1.8 * float(np.hypot(G[gi].real, G[gi].imag)), 1.4)
        xmin = min(-2.4 * base, -1.3)
        xmax = max(0.9 * base, 0.8)
        ylim = max(1.15 * base, 1.2)
        if df is not None:
            for c in (df.get("cycles") or []):
                if c["G"].real < xmin:
                    xmin = 1.15 * c["G"].real
        # 积分环节：ω→0 时 G→∞，Nyquist 轮廓在原点绕行的小半圆
        # 映射为 G 平面上的无穷大半圆；在坐标边缘用虚线示意补线。
        den_arr = np.asarray(d["den"], float)
        has_int = abs(den_arr[-1]) < 1e-9 * max(1.0, float(np.max(np.abs(den_arr))))
        if has_int:
            Rarc = 1.03 * max(abs(xmin), abs(xmax), ylim)
            th = np.linspace(-np.pi / 2, np.pi / 2, 320)
            B.plot(Rarc * np.cos(th), Rarc * np.sin(th), "--", lw=1.1,
                   color="#8e44ad", alpha=.75, label="积分环节补线（∞）")
            _k = int(np.argmin(np.abs(th - (np.pi / 2 - 0.45))))
            B.annotate("", xy=(Rarc * np.cos(th[_k - 1]), Rarc * np.sin(th[_k - 1])),
                       xytext=(Rarc * np.cos(th[_k + 1]), Rarc * np.sin(th[_k + 1])),
                       arrowprops=dict(arrowstyle="-|>", color="#8e44ad",
                                       lw=1.0, shrinkA=0, shrinkB=0))
            xmax = max(xmax, Rarc * 1.04)
            ylim = max(ylim, Rarc * 1.04)
        # 视野留白 + 缩放：1x 为适配；0.1x 扩大 10 倍，10x 放大 10 倍
        try:
            z = float(zoom)
        except Exception:
            z = 1.0
        z = min(10.0, max(0.1, z))
        span_x = max(abs(xmin), abs(xmax), 1.0)
        span_y = max(ylim, 1.0)
        half_x = 1.22 * span_x / z
        half_y = 1.22 * span_y / z
        # 以 (-0.5, 0) 为中心，放大时同时保住原点与 (-1,j0)
        B.set_xlim(-0.5 - half_x, -0.5 + half_x)
        B.set_ylim(-half_y, half_y)
        B.legend(fontsize=7, frameon=False, loc="lower left")
        B.grid(alpha=0.25, lw=0.5)
    else:
        uc = d["uc"]
        z = uc["roots"]
        B.add_patch(Circle((0, 0), 1.0, fill=False, ls="--", lw=1.0,
                           color="0.55"))
        B.axhline(0, color="k", lw=0.6)
        B.axvline(0, color="k", lw=0.6)
        B.plot(z.real, z.imag, "o", ms=7, mfc="#d1372c", mec="white",
               mew=1.1, zorder=5)
        B.set_title("单位圆：max|z| = %.3f -> %s"
                    % (uc["rmax"],
                       "临界稳定" if uc.get("marginal")
                       else ("稳定" if uc["stable"] else "不稳定")),
                    fontsize=9.5,
                    color=warn if uc.get("marginal") else ink)
        B.set_xlim(-1.25, 1.25)
        B.set_ylim(-1.25, 1.25)
        B.set_aspect("equal")
        B.grid(alpha=0.25, lw=0.5)

    # ---------------- (c) Bode 相位穿越
    C = axs[2]
    if not discrete:
        bc = d["bode"]
        w = bc["w"]
        mag = 20 * np.log10(np.maximum(bc["mag"], 1e-12))
        C.plot(w, mag, color="#1f6fb4", lw=1.3)
        C.axhline(0, color="k", lw=0.7)
        for wx in bc["wc"]:
            C.plot([wx], [0], "o", ms=6, color="#d1372c")
        C.set_xscale("log")
        C.set_ylabel("$20\\lg|G|$ (dB)", fontsize=8.5)
        C2 = C.twinx()
        C2.plot(w, bc["ph"], color="#8e44ad", lw=1.2)
        C2.axhline(-180, color="0.5", lw=0.8, ls="--")
        for wx in bc["wg"]:
            C2.plot([wx], [-180], "o", ms=6, mfc="none", color="#8e44ad")
        C2.set_ylabel("$\\angle G$ (deg)", fontsize=8.5, color="#8e44ad")
        C2.set_ylim(min(-185.0, float(np.min(bc["ph"])) - 5), 5)
        C.set_title("Bode：ω_c=%s，ω_g=%s"
                    % ("/".join("%.3g" % x for x in bc["wc"]) or "—",
                       "/".join("%.3g" % x for x in bc["wg"]) or "—"),
                    fontsize=9.5, color=ink)
        C.grid(alpha=0.25, lw=0.5, which="both")
        C.tick_params(labelsize=7.5)
        C2.tick_params(labelsize=7.5)
    else:
        T = float(d.get("T") or 1.0)
        w = np.logspace(-2, np.log10(np.pi / T), 900)
        zz = np.exp(1j * w * T)
        H = _peval(np.asarray(d["num"], float), zz) / _peval(np.asarray(d["den"], float), zz)
        ah = np.abs(H)
        C.plot(w, 20 * np.log10(np.maximum(ah, 1e-12)), color="#1f6fb4", lw=1.3)
        C.axhline(0, color="k", lw=0.7)
        C.set_xscale("log")
        C.set_ylabel("$20\\lg|G(e^{j\\omega T})|$ (dB)", fontsize=8.5)
        C3 = C.twinx()
        C3.plot(w, np.degrees(np.unwrap(np.angle(H))), color="#8e44ad", lw=1.1)
        C3.set_ylabel("$\\angle G$ (deg)", fontsize=8.5, color="#8e44ad")
        C.set_title("离散频率响应（0 ~ $\\pi/T$ = %.3g）" % (np.pi / T),
                    fontsize=9.5, color=ink)
        C.grid(alpha=0.25, lw=0.5, which="both")
        C.tick_params(labelsize=7.5)
        C3.tick_params(labelsize=7.5)

    # ---------------- (d) 闭环极点 / 离散 Jury 表
    D = axs[3]
    if not discrete:
        ch = d.get("ch")
        if ch is not None:
            rt = np.roots(np.asarray(ch, dtype=float))
            m = np.max(np.abs(rt)) if rt.size else 1.0
            lim = 1.25 * max(1.0, m)
            D.add_patch(__import__("matplotlib").patches.Rectangle(
                (0, -lim), lim, 2 * lim, facecolor="#fdecea", edgecolor="none",
                zorder=0))
            D.axhline(0, color="k", lw=0.6)
            D.axvline(0, color="k", lw=0.6)
            stable_mask = rt.real < -1e-9
            axis_mask = np.abs(rt.real) <= 1e-9
            if np.any(stable_mask):
                D.plot(rt.real[stable_mask], rt.imag[stable_mask], "o", ms=8,
                       mfc="#1f6fb4", mec="white", mew=1.2, zorder=5)
            if np.any(axis_mask):
                D.plot(rt.real[axis_mask], rt.imag[axis_mask], "o", ms=8,
                       mfc=warn, mec="white", mew=1.2, zorder=6)
            if np.any(~stable_mask & ~axis_mask):
                D.plot(rt.real[~stable_mask & ~axis_mask],
                       rt.imag[~stable_mask & ~axis_mask], "o", ms=8,
                       mfc="#d1372c", mec="white", mew=1.2, zorder=5)
            nr = int(np.sum(rt.real > 1e-9))
            nz = int(np.sum(axis_mask))
            D.set_title("闭环极点：%d 个（右半平面 %d 个，虚轴/原点 %d 个）"
                        % (rt.size, nr, nz),
                        fontsize=9.5, color=warn if nz else ink)
            D.set_xlim(-lim, lim)
            D.set_ylim(-lim, lim)
            D.set_aspect("equal")
            D.grid(alpha=0.25, lw=0.5)
            D.tick_params(labelsize=7.5)
    else:
        D.axis("off")
        D.set_title("Jury 表（逐行降阶）", fontsize=9.5, color=ink)
        rows = d["jury"]["rows"][:6]
        y = 0.90
        for i, row in enumerate(rows):
            txt = "  ".join("%.3g" % v for v in row[:6])
            D.text(0.03, y, "R%d:  %s" % (i + 1, txt), fontsize=7.6, color=ink,
                   va="center")
            y -= 0.13
        D.set_xlim(0, 1)
        D.set_ylim(0, 1)

    # 总标题
    st = d.get("stable")
    mg = bool(d.get("marginal"))
    if st is None:
        ttl = "稳定性判据"
    elif mg:
        ttl = "稳定性判据：闭环临界稳定（极点落在虚轴/原点）"
    else:
        ttl = "稳定性判据：" + ("闭环稳定" if st else "闭环不稳定")
    fig.suptitle(ttl, fontsize=11,
                 color=warn if mg else (good if st else bad), y=0.965)
    return axs
