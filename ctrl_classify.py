# -*- coding: utf-8 -*-
"""
校正环节自动识别：判断 Gc 是什么补偿器，并给出参数。

判据（连续 / 离散通用）：
    · 把零点与极点按“对数频率最近”配对，每对比较 |z| 与 |p|
        |z| < |p|  → 超前（零点更靠近虚轴 / 更靠近原点）
        |z| > |p|  → 滞后
    · 一对 → 一阶超前/滞后；两对及以上 → 多级串联、滞后-超前、双超前…
    · 有复极点 → 二阶谐振；原点极点 → 积分；原点零点 → 微分

对外：
    analyse(num, den, discrete=False) -> dict
    detect_domain(g0_text, gc_text, T_text) -> (domain, note)
    report(comp) -> list[str]
"""
from __future__ import annotations

import re

import numpy as np

TOL = 1e-6


def _roots(c):
    c = np.trim_zeros(np.asarray(c, float), "f")
    return np.roots(c) if c.size > 1 else np.array([])


def _clean(r):
    out = []
    for x in r:
        re_, im_ = x.real, x.imag
        if abs(re_) < TOL * max(1.0, abs(x)):
            re_ = 0.0
        if abs(im_) < TOL * max(1.0, abs(x)):
            im_ = 0.0
        out.append(complex(round(re_, 10), round(im_, 10)))
    out.sort(key=lambda z: (z.real, -z.imag))
    return np.array(out, complex)


def _fz(z, nd=4):
    if abs(z.imag) < TOL:
        return f"{z.real:.{nd}g}"
    s = "+" if z.imag >= 0 else "-"
    return f"{z.real:.{nd}g} {s} j{abs(z.imag):.{nd}g}"


def phi_max(alpha):
    """一阶网络（极零频率比 alpha>1）的最大相位差，度"""
    alpha = max(float(alpha), 1.0 + 1e-12)
    return float(np.degrees(np.arcsin((alpha - 1) / (alpha + 1))))


def _pair(zs, ps):
    """按对数频率最近配对；返回 [(z, p, 'lead'|'lag'|'none', ratio)]"""
    zs, ps = sorted(zs), sorted(ps)
    used, pairs = set(), []
    for z in zs:
        cands = [(abs(np.log(p / z)), i) for i, p in enumerate(ps) if i not in used]
        if not cands:
            pairs.append((z, None, "none", 1.0))
            continue
        _, i = min(cands)
        used.add(i)
        p = ps[i]
        pairs.append((z, p, "lead", p / z) if z < p else (z, p, "lag", z / p))
    for i, p in enumerate(ps):
        if i not in used:
            pairs.append((None, p, "none", 1.0))
    return pairs


def analyse(num, den, discrete=False):
    num = np.asarray(num, float)
    den = np.asarray(den, float)
    if num.size == 0 or den.size == 0 or not np.any(num):
        return dict(kind="none", title="无校正环节", lines=[], zeros=np.array([]),
                    poles=np.array([]), dc=1.0, gain=1.0)

    k = num[0] / den[0]
    zeros, poles = _clean(_roots(num)), _clean(_roots(den))
    nz, npl = zeros.size, poles.size
    plane = "z" if discrete else "s"

    xv = 1.0 if discrete else 0.0
    dv = np.polyval(den, xv)
    dc = float("inf") if abs(dv) < 1e-12 else float(np.polyval(num, xv) / dv)

    lines = []
    cplx_p = [p for p in poles if abs(p.imag) >= TOL]
    real_z = [abs(z.real) for z in zeros if abs(z.imag) < TOL]
    real_p = [abs(p.real) for p in poles if abs(p.imag) < TOL]
    p_origin = [p for p in poles if abs(p) < 1e-9]
    z_origin = [z for z in zeros if abs(z) < 1e-9]

    if nz == 0 and npl == 0:
        return dict(kind="gain", title="纯比例（增益）环节",
                    lines=[f"增益 K = {abs(dc):.4g}" + ("" if dc >= 0 else "（反号）")],
                    zeros=zeros, poles=poles, dc=dc, gain=k)

    if cplx_p:
        p0 = max(cplx_p, key=lambda z: z.imag)
        wn = abs(p0)
        lines.append(f"极点 {plane} = {_fz(p0)}、{_fz(p0.conjugate())}")
        if not discrete:
            lines.append("ω_n = %.4g rad/s，ζ = %.3f（ζ<0.7 会在 ω_n 附近起峰，吃掉相角裕度）"
                         % (wn, -p0.real / wn))
        lines.append(f"直流增益 = {dc:.4g}")
        return dict(kind="second-order", title="二阶振荡（谐振）环节", lines=lines,
                    zeros=zeros, poles=poles, dc=dc, gain=k)

    if p_origin:
        order = len(p_origin)
        lines.append(f"{plane} = 0 处 {order} 重极点 → 型别 +{order}（消阶跃/斜坡稳态误差）")
        if real_z:
            lines.append("零点 " + "、".join(_fz(z) for z in zeros))
            lines.append("其余极点 " + ("、".join(_fz(p) for p in poles if abs(p) > 1e-9) or "无"))
        lines.append(f"直流增益 = {'∞' if not np.isfinite(dc) else f'{dc:.4g}'}")
        return dict(kind="integrator",
                    title="纯积分环节" if order == 1 and not real_z else
                          f"含 {order} 重积分的补偿器",
                    lines=lines, zeros=zeros, poles=poles, dc=dc, gain=k)

    if z_origin and npl:
        lines.append(f"{plane} = 0 处零点 → 微分作用")
        lines.append("极点 " + "、".join(_fz(p) for p in poles if abs(p) > 1e-9))
        lines.append(f"直流增益 = {dc:.4g}")
        return dict(kind="pd", title="PD 型（含微分）", lines=lines, zeros=zeros,
                    poles=poles, dc=dc, gain=k)

    if nz >= 1 and npl == 0:
        lines.append("零点 " + "、".join(_fz(z) for z in zeros))
        lines.append(f"高频增益 {abs(k):.4g}（{plane}→∞ 不衰减，纯微分/超前）")
        lines.append(f"直流增益 = {dc:.4g}")
        return dict(kind="pd", title=f"{nz} 阶微分（PD）环节", lines=lines,
                    zeros=zeros, poles=poles, dc=dc, gain=k)

    if nz == 0 and npl >= 1:
        lines.append("极点 " + "、".join(_fz(p) for p in poles))
        lines.append("转折频率 " + "、".join(f"{abs(p):.4g}" for p in poles) + " rad/s")
        lines.append("只会滞后相位，不能用来补相角裕度")
        lines.append(f"直流增益 = {dc:.4g}")
        return dict(kind="lowpass",
                    title="一阶低通（惯性）滤波环节" if npl == 1 else f"{npl} 阶低通滤波环节",
                    lines=lines, zeros=zeros, poles=poles, dc=dc, gain=k)

    # ---- 实零极点配对
    pairs = _pair(sorted(real_z), sorted(real_p))
    valid = [p for p in pairs if p[0] is not None and p[1] is not None]
    extra_z = [p[0] for p in pairs if p[1] is None]
    extra_p = [p[1] for p in pairs if p[0] is None]
    kinds = [p[2] for p in valid]
    n_lead, n_lag = kinds.count("lead"), kinds.count("lag")

    if not valid:
        lines.append("零点 " + ("、".join(_fz(z) for z in zeros) or "无"))
        lines.append("极点 " + ("、".join(_fz(p) for p in poles) or "无"))
        lines.append(f"直流增益 = {dc:.4g}")
        return dict(kind="general", title="一般有理校正环节", lines=lines,
                    zeros=zeros, poles=poles, dc=dc, gain=k)

    if len(valid) == 1:
        z, p, kind, ratio = valid[0]
        wm, pm = float(np.sqrt(z * p)), phi_max(ratio)
        lines.append(f"零点 {plane} = -{z:.4g}，极点 {plane} = -{p:.4g}")
        tail = "（按连续近似，离散实际略小）" if discrete else ""
        if kind == "lead":
            kind_out, title = "lead", "一阶超前校正"
            lines.append(f"分度系数 α = |p|/|z| = {ratio:.3f}")
            lines.append(f"最大超前角 +{pm:.2f}° @ ω ≈ {wm:.4g} rad/s{tail}")
        else:
            kind_out, title = "lag", "一阶滞后校正"
            lines.append(f"分度系数 β = |z|/|p| = {ratio:.3f}")
            lines.append(f"最大滞后角 -{pm:.2f}° @ ω ≈ {wm:.4g} rad/s{tail}")
    else:
        if n_lead and n_lag:
            kind_out, title = "lead-lag", "滞后-超前（双频段）校正"
        elif n_lead:
            kind_out, title = "lead", f"{len(valid)} 级超前环节串联"
        elif n_lag:
            kind_out, title = "lag", f"{len(valid)} 级滞后环节串联"
        else:
            kind_out, title = "general", "多级一阶环节串联"
        for (z, p, kind, ratio) in sorted(valid, key=lambda q: np.sqrt(q[0] * q[1])):
            wm, pm = float(np.sqrt(z * p)), phi_max(ratio)
            tag = "超前" if kind == "lead" else "滞后"
            lines.append("%s级：零点 -%.4g / 极点 -%.4g（%s=%.2f，最大 ±%.1f° @ %.3g rad/s）"
                         % (tag, z, p, "α" if kind == "lead" else "β", ratio, pm, wm))
        if extra_z:
            lines.append("多出零点 → 附带微分：" + "、".join(f"-{z:.4g}" for z in extra_z))
        if extra_p:
            lines.append("多出极点 → 附带低通：" + "、".join(f"-{p:.4g}" for p in extra_p))

    lines.append("零点 " + ("、".join(_fz(z) for z in zeros) or "无")
                 + "；极点 " + ("、".join(_fz(p) for p in poles) or "无"))
    lines.append(f"直流增益 Gc({1 if discrete else 0}) = {dc:.4g}")
    return dict(kind=kind_out, title=title, lines=lines, zeros=zeros, poles=poles,
                dc=dc, gain=k)


def detect_domain(g0_text, gc_text, T_text):
    """按输入里出现的变量自动判断连续/离散"""
    z_re = re.compile(r"(?<![A-Za-z])z(?![A-Za-z])")
    s_re = re.compile(r"(?<![A-Za-z])s(?![A-Za-z])")
    has_z = bool(z_re.search(g0_text or "")) or bool(z_re.search(gc_text or ""))
    has_s = bool(s_re.search(g0_text or "")) or bool(s_re.search(gc_text or ""))
    has_T = bool((T_text or "").strip())
    if has_T:
        return "discrete", "填了采样周期 T ⇒ 离散系统"
    if has_z and has_s:
        return "discrete", "同时出现 s 与 z（对象 s 域 + 校正器 z 域）⇒ 离散"
    if has_z:
        return "discrete", "式子里出现 z ⇒ 离散系统（记得填 T）"
    return "continuous", "式子里只有 s ⇒ 连续系统"


def report(comp):
    if comp is None or comp.get("kind") == "none":
        return []
    return [comp.get("title", "")] + comp.get("lines", [])


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    import ctrl_check as cc

    txt = sys.argv[1] if len(sys.argv) > 1 else "(2s+1)/(0.5s+1)"
    n, d = cc.to_numden(txt)
    print("\n".join(report(analyse(n, d))))
