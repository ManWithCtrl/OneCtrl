# -*- coding: utf-8 -*-
"""
根轨迹（root locus）—— 连续 / 离散通用

    L(s) = N(s)/D(s)，闭环特征式  D(s) + K·N(s) = 0

    K: 0 → ∞ 时闭环极点的轨迹；K = 0 起于开环极点，K → ∞ 终于开环零点（或无穷远）

连续模式下额外给出：渐近线（交点/倾角）、实轴分离点、虚轴交点及临界增益、出射角
离散模式下额外给出：单位圆交点及临界增益（|z| = 1 ⇔ 临界稳定）

命令行：
    python ctrl_rootlocus.py -g0 "10/(s*(s+1))"
    python ctrl_rootlocus.py -g0 "10/(s*(s+1))" -gc "(s+1)/(s+8)"
    python ctrl_rootlocus.py -g0 "10/(s*(s+1))" -gc "(z-0.8)/(z-0.3)" -T 0.1
"""
import argparse
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ctrl_check import _polyadd_same


def _polyder(a):
    return np.polyder(np.asarray(a, float))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                              # noqa: BLE001
        pass


# ---------------------------------------------------------------- 轨迹
def locus(num, den, npts=900, kmax=1e4):
    """返回 (Ks, roots[npts, n])，已按最近邻配对排序（不会跨支跳）"""
    num = np.asarray(num, float)
    den = np.asarray(den, float)
    # 去掉公共的首项缩放，保证 D + K·N 同阶
    n = len(den) - 1
    if len(num) < len(den):
        num = np.concatenate([np.zeros(len(den) - len(num)), num])
    Ks = np.concatenate([
        np.logspace(np.log10(1e-4), np.log10(1.0), npts // 3, endpoint=False),
        np.linspace(1.0, 50.0, npts // 3, endpoint=False),
        np.logspace(np.log10(50.0), np.log10(kmax), npts - 2 * (npts // 3)),
    ])
    roots = np.empty((len(Ks), n), dtype=complex)
    prev = None
    for i, K in enumerate(Ks):
        c = _polyadd_same(den, K * num)
        r = list(np.roots(c))
        if prev is None:
            r = sorted(r, key=lambda q: (q.real, q.imag))
        else:
            out = []
            for p in prev:
                j = min(range(len(r)), key=lambda k: abs(r[k] - p))
                out.append(r.pop(j))
            r = out
        roots[i] = r
        prev = r
    return Ks, roots


# ---------------------------------------------------------------- 指标
def asymptotes(num, den):
    """渐近线：交点与倾角（仅连续有意义）"""
    p = np.roots(den)
    z = np.roots(num) if len(np.trim_zeros(num, "f")) > 1 else np.array([])
    n, m = len(p), len(z)
    if n <= m:
        return None, None
    cen = float(np.real((p.sum() - z.sum()) / (n - m)))
    ang = [(2 * k + 1) * 180.0 / (n - m) for k in range(n - m)]
    return cen, sorted(ang)


def breakaway(num, den):
    """实轴分离点：dK/ds = 0 → N'D − N D' = 0，取 K > 0 的实根"""
    N = np.asarray(num, float)
    D = np.asarray(den, float)
    n = len(D) - 1
    if len(N) < len(D):
        N = np.concatenate([np.zeros(len(D) - len(N)), N])
    poly = np.polysub(np.polymul(_polyder(N), D), np.polymul(N, _polyder(D)))
    out = []
    for r in np.roots(poly):
        if abs(r.imag) < 1e-6:
            x = r.real
            if abs(np.polyval(N, x)) < 1e-12:
                continue
            K = -np.polyval(D, x) / np.polyval(N, x)
            if K > 0:
                out.append((x, K))
    return sorted(out)


def axis_crossing(num, den, discrete=False, T=1.0):
    """连续：虚轴交点；离散：单位圆交点。返回 [(ω 或 幅角, K)]"""
    Ks, roots = locus(num, den, npts=3000, kmax=1e6)
    out = []
    for i in range(len(Ks) - 1):
        a, b = roots[i], roots[i + 1]
        for j in range(a.shape[0]):
            if discrete:
                fa = abs(a[j]) - 1.0
                fb = abs(b[j]) - 1.0
            else:
                fa = a[j].real
                fb = b[j].real
            if fa * fb < 0:
                # 二分细化
                k0, k1 = Ks[i], Ks[i + 1]
                for _ in range(40):
                    km = 0.5 * (k0 + k1)
                    rm = np.roots(_polyadd_same(
                        np.asarray(den, float),
                        km * np.concatenate([np.zeros(len(den) - len(num)), num])))
                    rm = rm[np.argmin(np.abs(rm - a[j]))]
                    fm = (abs(rm) - 1.0) if discrete else rm.real
                    if fa * fm <= 0:
                        k1 = km
                    else:
                        k0 = km
                km = 0.5 * (k0 + k1)
                rm = np.roots(_polyadd_same(
                    np.asarray(den, float),
                    km * np.concatenate([np.zeros(len(den) - len(num)), num])))
                rm = rm[np.argmin(np.abs(rm - a[j]))]
                out.append((rm, km))
    return out


def departure_angles(pole, poles, zeros):
    """复数极点的出射角（度）"""
    tot = 180.0
    for z in zeros:
        tot += np.degrees(np.angle(pole - z))
    for q in poles:
        if abs(q - pole) > 1e-9:
            tot -= np.degrees(np.angle(pole - q))
    return (tot + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------- 画图
def draw(ax, num, den, discrete=False, T=1.0, k_mark=1.0, title=""):
    Ks, roots = locus(num, den)
    ax.axhline(0, color="k", lw=0.7, zorder=1)
    ax.axvline(0, color="k", lw=0.7, zorder=1)

    if discrete:
        th = np.linspace(0, 2 * np.pi, 400)
        ax.fill_between(np.cos(th) * 0 + np.cos(th), np.sin(th), 1.5,
                        color="0.95", zorder=0)
        ax.plot(np.cos(th), np.sin(th), "--", color="0.4", lw=1.0, zorder=2)

    poles = np.roots(den)
    zeros = np.roots(num) if len(np.trim_zeros(num, "f")) > 1 else np.array([])
    c1 = _polyadd_same(np.asarray(den, float), k_mark * np.asarray(num, float))
    r1 = np.roots(c1)

    # 视野：按开环零极点与 K=1 闭环极点定，别被大 K 的远处分支撑爆
    if discrete:
        box = 1.35
    else:
        # 以“离虚轴最近的那对闭环极点”定视野：根轨迹图的重点在原点附近，
        # 远处的大极点会把画面压扁
        cand = np.abs(r1) if r1.size else np.array([])
        cand = cand[cand > 1e-9]
        r0 = cand.min() if cand.size else max(1.0, np.abs(poles).max())
        box = max(1.0, 2.0 * r0)

    # 轨迹：按 K 上色（浅 → 深），只画视野内的部分
    cmap = plt.get_cmap("viridis")
    for j in range(roots.shape[1]):
        q = roots[:, j]
        m = (np.abs(q.real) < 2.2 * box) & (np.abs(q.imag) < 2.2 * box)
        ax.scatter(q.real[m], q.imag[m], s=2.4, c=np.log10(Ks)[m],
                   cmap=cmap, vmin=np.log10(Ks[0]), vmax=np.log10(Ks[-1]),
                   zorder=3, linewidths=0)

    ax.plot(poles.real, poles.imag, "x", ms=11, mew=2.2, color="#c0392b",
            zorder=6, label="开环极点 (K=0)")
    if zeros.size:
        ax.plot(zeros.real, zeros.imag, "o", ms=9, mfc="none", mew=1.8,
                color="#2c8a3e", zorder=6, label="开环零点 (K→∞)")
    ax.plot(r1.real, r1.imag, "*", ms=13, color="#8e44ad", zorder=7,
            label="K = %g 的闭环极点" % k_mark)

    # 渐近线（连续）
    if not discrete:
        cen, ang = asymptotes(num, den)
        if cen is not None:
            rmax = 1.25 * box
            for a in ang:
                ax.plot([cen, cen + rmax * np.cos(np.radians(a))],
                        [0, rmax * np.sin(np.radians(a))],
                        ":", color="0.55", lw=1.0, zorder=2)
            ax.plot([cen], [0], "+", ms=9, color="0.45", zorder=4)
        for x, K in breakaway(num, den):
            ax.plot([x], [0], "D", ms=6, color="#d4ac0d", zorder=6)
        for r, K in axis_crossing(num, den, discrete=False):
            ax.plot([0], [r.imag], "o", ms=6, mfc="none", mew=1.6,
                    color="#7d3c98", zorder=6)

    ax.set_xlim(-box, box)
    ax.set_ylim(-box, box)
    ax.set_aspect("equal")
    ax.set_xlabel("Re")
    ax.set_ylabel("Im")
    ax.set_title(title or ("根轨迹（z 平面）" if discrete else "根轨迹（s 平面）"),
                 fontsize=9.5, pad=6)
    ax.grid(True, alpha=0.22, lw=0.5)
    ax.legend(fontsize=7.2, loc="upper right", framealpha=0.9)
    return ax


def main():
    from ctrl_zcheck import _coeffs, _parse, _trim
    import sympy as sp
    ss = sp.Symbol("s")
    ap = argparse.ArgumentParser(description="根轨迹（连续 / 离散）")
    ap.add_argument("-g0", required=True)
    ap.add_argument("-gc", default="")
    ap.add_argument("-T", type=float, default=None, help="给了 T 就是离散（z 平面）")
    ap.add_argument("-K", type=float, default=1.0, help="要标记的增益点，默认 1")
    ap.add_argument("-o", "--out", default="rlocus.png")
    a = ap.parse_args()

    n0, d0 = _coeffs(_parse(a.g0, ss, "s"), ss)
    n0, d0 = _trim(n0), _trim(d0)
    if a.T is None:
        if a.gc.strip():
            n1, d1 = _coeffs(_parse(a.gc, ss, "s"), ss)
            num, den = np.polymul(n1, n0), np.polymul(d1, d0)
        else:
            num, den = n0, d0
        discrete = False
    else:
        import ctrl_zcheck as cz
        d = cz.analyse(a.g0, a.gc, a.T)
        num, den = d["num"], d["den"]
        discrete = True

    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    draw(ax, num, den, discrete=discrete, T=a.T or 1.0, k_mark=a.K)
    fig.tight_layout()
    fig.savefig(a.out, dpi=150, facecolor="white")
    print("图已保存：", a.out)

    cen, ang = (None, None) if discrete else asymptotes(num, den)
    if cen is not None:
        print("渐近线交点 σ_a = %.4f, 倾角 = %s" % (float(np.real(cen)), ["%.0f°" % x for x in ang]))
    for x, K in ([] if discrete else breakaway(num, den)):
        print("实轴分离/会合点 s = %.4f (K = %.4f)" % (x, K))
    for r, K in axis_crossing(num, den, discrete, a.T or 1.0):
        if discrete:
            print("单位圆交点 z = %.4f%+.4fj (K = %.4f)" % (r.real, r.imag, K))
        else:
            print("虚轴交点 s = %+.4fj (K = %.4f)" % (r.imag, K))


if __name__ == "__main__":
    main()
