#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ctrl_app.py —— 控制系统校正验算器（桌面 GUI，tkinter）

依赖：numpy / sympy / matplotlib（与 ctrl_check.py 相同，无需额外安装）

启动：
    python ctrl_app.py
或双击（Windows 下可把后缀改成 .pyw 隐藏黑框）

功能：
    * 输入原开环 G0(s) 与校正环节 Gc(s)（普通表达式或 LaTeX 均可）
    * 一键给出 Bode 对比、闭环阶跃、零极点分布
    * 终端/窗口内同时列出 ω_c、γ、K_g、σ、t_p、t_s、ζ、ω_n、稳态误差
"""

import sys
import threading
import traceback

import numpy as np

import ctrl_check as cc  # 复用内核：to_expr / analyse / step_response ...
import ctrl_zcheck as czl  # 离散（采样）版本内核
import ctrl_nonlinear as cnl  # 非线性环节闭环仿真
import ctrl_rootlocus as crl  # 根轨迹

import matplotlib

# tkinter 只在"真正开窗口"时才需要。服务器（无 X / 没装 python3-tk）上
# ctrl_web.py 只借用本模块的计算内核（compute / draw / metrics_text），
# 所以这里把 GUI 相关的 import 全部做成"可选"，缺了也不影响计算。
try:
    matplotlib.use("TkAgg", force=True)
    from matplotlib.backends.backend_tkagg import (  # noqa: E402
        FigureCanvasTkAgg, NavigationToolbar2Tk)
    import tkinter as tk  # noqa: E402
    from tkinter import ttk, messagebox, filedialog  # noqa: E402
    HAS_GUI = True
except Exception:                       # noqa: BLE001
    HAS_GUI = False
    FigureCanvasTkAgg = NavigationToolbar2Tk = None
    ttk = messagebox = filedialog = None

    class _FakeTk:                       # 占位基类，保证 class App(...) 能定义
        def __init__(self, *a, **kw):
            raise RuntimeError(
                "没有 tkinter，无法开桌面窗口。\n"
                "Ubuntu/Debian: sudo apt install python3-tk\n"
                "（若只是用网页版，可忽略本错误）")

    class _FakeTkModule:
        Tk = _FakeTk

    tk = _FakeTkModule()

from matplotlib.figure import Figure  # noqa: E402


PRESETS = {
    "示例 1：超前校正（Bode 设计题）":
        ("100*(0.1s+1)/((s+1)*(0.2s+1)*(0.02s+1))", "(s/12.12+1)/(s/70.34+1)"),
    "示例 2：滞后校正（增益翻倍）":
        ("10*(s/2+1)/(s*(s+1)*(s/20+1))", "2*(s+1)/(2s+1)"),
    "示例 3：LaTeX 输入（I 型系统）":
        (r"\frac{10}{s(s+1)}", r"\frac{2s+1}{0.5s+1}"),
    "示例 4：无校正（只分析原系统）":
        ("10/(s*(s+1)*(0.5s+1))", ""),
    "示例 5：离散校正（T = 0.1 s，D(z)）":
        ("10/(s*(s+1))", "(z-0.8)/(z-0.3)", "0.1"),
    "示例 6：离散校正（Gc 用 s 写，Tustin）":
        ("10/(s*(s+1))", "(s+1)/(s+8)", "0.1"),
}


# ---------------------------------------------------------------- 计算内核
def _apply_input(t, y_step, kind):
    """把单位阶跃响应积成斜坡/加速度响应（LTI：Y(s)=G/s^k）"""
    t = np.asarray(t, float)
    y = np.asarray(y_step, float)
    if kind == "ramp":
        y = np.concatenate([[0.0], np.cumsum(0.5 * (y[1:] + y[:-1])
                                            * np.diff(t))])
    elif kind == "accel":
        v = np.concatenate([[0.0], np.cumsum(0.5 * (y[1:] + y[:-1])
                                            * np.diff(t))])
        y = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1])
                                            * np.diff(t))])
    return y


def _input_signal(t, kind):
    t = np.asarray(t, float)
    return {"step": np.ones_like(t), "ramp": t, "accel": 0.5 * t * t}[kind]


def _guard(num, den):
    """拦截假分式（分子阶次 >= 分母阶次）——闭环阶跃无界，没有意义。"""
    if len(num) > len(den):
        raise ValueError(
            "开环必须是真分式（分母阶次 >= 分子阶次）。当前分子 %d 阶、分母 %d 阶"
            "（例如 Gc=(s+1)^2 这种纯零点环节）——它对应的不是可实现的系统。"
            "请把 Gc 写成分母也有极点形式，或让 G0 多带一个极点（如 1/(s*(s+1))）。"
            % (len(num) - 1, len(den) - 1))


def compute(g0_text, gc_text, kind="step", nl="none", M=1.0, a=1.0):
    """只做数值计算，返回 data 字典（不碰任何 matplotlib 对象）。

    nl != "none" 时，闭环响应改为「非线性环节 + 线性对象」的时域仿真
    （relay / relay_dz / sat），见 ctrl_nonlinear.py。
    """
    res, num, den, w = cc.analyse(g0_text, gc_text)
    _guard(num, den)
    n0, d0 = res["raw"]["num"], res["raw"]["den"]
    nl = (nl or "none").strip()
    nl_on = nl not in ("", "none")

    if len(den) == 1:                     # 纯增益：闭环只是常数 K/(1+K)
        K = float(num[0]) / float(den[0])
        if nl_on:
            t, y, u, desc = cnl.simulate(num, den, kind, nl, M=M, a=a)
            yinf = float(np.mean(y[-max(3, len(y) // 20):]))
            met = cc.time_metrics(t, y, y_inf=yinf) if kind == "step" else None
            return {"t": t, "y": y, "y_step": y, "u": u, "met": met, "dp": None,
                    "stable": True, "num": np.asarray(num, float),
                    "den": np.asarray(den, float), "cl_den": np.asarray(den, float),
                    "w": w, "res": res, "y_inf": yinf, "kind": kind,
                    "kp": K, "n_int": 0, "e_ss": float(1.0 - yinf) if kind == "step" else None,
                    "poles_ol": np.array([]), "zeros_ol": np.array([]),
                    "roots_cl": np.array([]), "nl": nl, "nl_desc": desc,
                    "r_raw": res["raw"], "r_cmp": res.get("cmp")}
        yinf = K / (1.0 + K) if abs(1.0 + K) > 1e-12 else float("inf")
        t = np.linspace(0, 1, 400)
        y = np.full_like(t, yinf)
        met = dict(sigma=0.0, tp=None, tr=0.0, ts=0.0)
        return {"t": t, "y": y, "met": met, "dp": None, "stable": True,
                "num": np.asarray(num, float), "den": np.asarray(den, float),
                "cl_den": np.asarray(den, float), "w": w, "res": res,
                "y_inf": yinf, "kind": kind, "kp": K, "n_int": 0,
                "e_ss": 1.0 - yinf if kind == "step" else None,
                "poles_ol": np.array([]), "zeros_ol": np.array([]),
                "roots_cl": np.array([]),
                "r_raw": res["raw"], "r_cmp": res.get("cmp")}

    if nl_on:
        t, y, u, desc = cnl.simulate(num, den, kind, nl, M=M, a=a)
        y_step = y
        _yinf = float(np.mean(y[-max(3, len(y) // 20):]))
        met = cc.time_metrics(t, y, y_inf=_yinf) if kind == "step" else None
    else:
        t, y = cc.step_response(num, den)
        y_step = y
        if kind != "step":
            y = _apply_input(t, y_step, kind)
        met = cc.time_metrics(t, y_step)
        if kind != "step":
            met = dict(met, sigma=None, tp=None, ts=None, tr=None)
        u = None
    cl_den = cc._polyadd_same(np.asarray(den, float), np.asarray(num, float))
    dp = cc.dominant_pair(cl_den)

    roots_cl = np.roots(cl_den)
    stable = bool(np.all(roots_cl.real < 1e-9))
    # 临界稳定：全部极点在闭左半平面，但至少一个正好落在虚轴上。
    marginal = bool(stable and np.any(np.abs(roots_cl.real) < 1e-9))
    if not stable:
        met = None        # 闭环不稳定时超调/调节时间无意义
    elif marginal:
        met = None        # 原点极点：阶跃响应为斜坡/等幅振荡，σ / t_s 无意义

    # 开环零点极点取“校正后”的（与 Bode 图那条曲线一致）
    poles_ol = np.roots(den) if len(den) > 1 else np.array([])
    zeros_ol = np.roots(num) if len(num) > 1 else np.array([])
    zeros_cl = zeros_ol

    # 稳态误差（单位阶跃）
    # 型别只看分母末尾的零系数（即 s 的幂次），中间为 0 的系数不是积分环节
    n_int = 0
    for c in d0[::-1]:
        if abs(c) < 1e-12:
            n_int += 1
        else:
            break
    dc0, dc1 = d0[-1], (d0[-2] if len(d0) >= 2 else 0.0)
    if n_int == 0:
        kp = dc0 and (n0[-1] / dc0) or float("inf")
    else:
        kp = float("inf")
    # 临界稳定时阶跃无有限稳态值（斜坡/等幅振荡），e_ss 不下结论
    if not np.isfinite(kp):
        e_ss = 0.0
    elif abs(1.0 + kp) < 1e-12:
        e_ss = float("inf")      # 1/(1+K_p) 分母为零：无有限稳态误差可言
    else:
        e_ss = 1.0 / (1.0 + kp)
    if nl_on:
        r = _input_signal(t, kind)
        e_ss = (float(1.0 - _yinf) if kind == "step"
                else float(r[-1] - y[-1]))
    elif kind != "step":
        r = _input_signal(t, kind)
        e_ss = float(r[-1] - y[-1])       # 末时刻跟踪误差
    elif marginal:
        e_ss = float("nan")               # 临界稳定：稳态误差无意义

    out = dict(kind=kind, y_step=y_step, r=_input_signal(t, kind),
               res=res, num=num, den=den, w=w, t=t, y=y, met=met, dp=dp,
               stable=stable, marginal=marginal, roots_cl=roots_cl, poles_ol=poles_ol,
               zeros_ol=zeros_ol, zeros_cl=zeros_cl,
               kp=kp, e_ss=e_ss, n_int=n_int, nl=nl)
    if nl_on:
        out.update(u=u, nl_desc=desc, y_inf=float(np.mean(y[-max(3, len(y) // 20):])))
    return out


def metrics_text(d, has_cmp):
    r_raw, r_cmp = d["res"]["raw"], d["res"]["cmp"]

    def omega_line(tag, r):
        wc = r["wc"][:1]
        gm = r["gm"][:1]
        ws = ", ".join(f"{x:.4g}" for x in wc) or "无 0 dB 交点"
        gs_ = ", ".join(f"{x:.2f}°" for x in gm) or "—"
        return f"{tag:<6s} ω_c = {ws:<22s} γ = {gs_}"

    L = []
    L.append("【开环 Bode 指标】")
    L.append(omega_line("校正前", r_raw))
    if has_cmp:
        L.append(omega_line("校正后", r_cmp))
    for tag, r in (("校正前", r_raw), ("校正后", r_cmp)):
        if tag == "校正后" and not has_cmp:
            continue
        if r["wg"].size:
            L.append(f"{tag:<6s} ω_g = {', '.join(f'{x:.4g}' for x in r['wg'][:3])}"
                     f"   K_g = {', '.join(cc.fmt(x, 2) + ' dB' for x in r['kg'][:3])}")
        else:
            L.append(f"{tag:<6s} 相位不穿越 -180°，K_g = ∞")
    if has_cmp and r_cmp["wc"].size and r_raw["wc"].size:
        ratio = r_cmp["wc"][0] / r_raw["wc"][0]
        dpm = r_cmp["gm"][0] - r_raw["gm"][0]
        L.append(f"{'变化':<6s} ω_c × {ratio:.3f}  ({20*np.log10(ratio):+.2f} dB)"
                 f"   γ {dpm:+.2f}°")

    L.append("")
    L.append("【闭环时域（单位阶跃）】")
    if d.get("nl", "none") not in ("", "none"):
        L.append("非线性环节  " + (d.get("nl_desc") or "非线性") + "（时域仿真）")
        L.append("说明：σ / t_p / t_s 由非线性仿真响应统计，不是线性指标")
    if np.isfinite(d["e_ss"]):
        L.append(f"稳态误差  e_ss = {d['e_ss']:.5f}  ({100*d['e_ss']:.2f}%)"
                 f"   型别 {'0' if d['n_int'] == 0 else 'I 型及以上'}"
                 f"   K_p = {d['kp']:.6g}")
    else:
        L.append("稳态误差  e_ss = —（无有限稳态：闭环临界稳定）"
                 f"   型别 {'0' if d['n_int'] == 0 else 'I 型及以上'}")
    if d.get("marginal"):
        L.append("⚠ 闭环临界稳定（极点落在虚轴/原点）：阶跃响应为斜坡或等幅振荡，"
                 "σ / t_s / y(∞) 均不定义")
        if d.get("dp"):
            z, wn, p = d["dp"]
            L.append(f"主导极点  {p.real:.3f} ± j{abs(p.imag):.3f}"
                     f"   →  ζ = {z:.3f},  ω_n = {wn:.4f}")
    elif d["stable"]:
        met, dp = d["met"], d["dp"]
        if met is None:
            L.append("响应指标  —（非阶跃输入不定义）")
        else:
            L.append(f"稳态值    y(∞) = {met['y_inf']:.5f}")
            if met.get("sigma") is None:
                L.append("超调量    —（非阶跃输入不定义）")
                L.append("峰值时间  —（非阶跃输入不定义）")
                L.append("调节时间  —（非阶跃输入不定义）")
            else:
                _sg, _tp, _ts = met["sigma"], met["tp"], met["ts"]
                L.append("超调量    σ = %.2f%%" % _sg if np.isfinite(_sg)
                         else "超调量    σ = （发散，无意义）")
                L.append("峰值时间  t_p = %.1f ms" % (_tp * 1000) if np.isfinite(_tp)
                         else "峰值时间  t_p = —")
                L.append("调节时间  t_s(2%%) = %.1f ms" % (_ts * 1000)
                         if np.isfinite(_ts)
                         else "调节时间  t_s(2%%) = —（仿真窗口内未进入 ±2%）")
        if dp:
            z, wn, p = dp
            L.append(f"主导极点  {p.real:.3f} ± j{abs(p.imag):.3f}"
                     f"   →  ζ = {z:.3f},  ω_n = {wn:.4f}")
        else:
            L.append("主导极点  纯实极点，阻尼比不适用")
    else:
        L.append("⚠ 闭环不稳定：σ / t_p / t_s / ζ 均无意义")

    L.append("")
    L.append("【极点零点（校正后开环）】")
    L.append("开环极点：" + _fmt_list(d["poles_ol"]))
    if d["zeros_ol"].size:
        L.append("开环零点：" + _fmt_list(d["zeros_ol"]))
    L.append("闭环极点：" + _fmt_list(d["roots_cl"]))
    L.append("")
    L.append("闭环" + ("临界稳定 ⚠" if d.get("marginal")
                       else ("稳定 ✔" if d["stable"] else "不稳定 ✘")))
    return "\n".join(L)


def _fmt_list(arr, nd=4):
    if arr.size == 0:
        return "—"
    out = []
    for v in np.sort_complex(arr):
        out.append(f"{v.real:.{nd}g}{v.imag:+.{nd}g}j" if abs(v.imag) > 1e-9
                   else f"{v.real:.{nd}g}")
    return ", ".join(out)


# ---------------------------------------------------------------- 绘图
# ---------------------------------------------------------------- 离散
def compute_z(g0_text, gc_text, T, kind="step", nl="none", M=1.0, a=1.0):
    """离散：G0 经零阶保持采样，Gc 可以是 D(z) 也可以是 D(s)（Tustin）。

    nl != "none" 时用 ctrl_nonlinear.simulate_z 做离散非线性闭环仿真，
    并覆盖 d["t"]/d["y"]，使绘图与指标反映非线性。
    """
    d = czl.analyse(g0_text, gc_text, T)
    d["_z"] = True
    nl = (nl or "none").strip()
    if nl not in ("", "none"):
        t, y, u, desc = cnl.simulate_z(d["num"], d["den"], T, kind=kind,
                                       nl=nl, M=M, a=a)
        d["t"], d["y"], d["u"] = t, y, u
        d["kind"] = kind
        d["nl"] = nl
        d["nl_desc"] = desc
        _yinf = float(np.mean(y[-max(3, len(y) // 20):]))
        d["met"] = cc.time_metrics(t, y, y_inf=_yinf) if kind == "step" else None
        d["y_inf"] = _yinf
        d["e_ss"] = float(1.0 - _yinf) if kind == "step" else None
    return d


def metrics_text_z(d, has_cmp):
    T = d["T"]
    L = []
    L.append("【离散开环指标】T = %g s，零阶保持" % T)
    if d.get("nl", "none") not in ("", "none"):
        L.append("非线性环节  " + (d.get("nl_desc") or "非线性") + "（逐拍时域仿真）")
        L.append("说明：σ / t_p / t_s 由非线性仿真响应统计，不是线性指标")
    L.append("Nyquist 频率  π/T = %.4g rad/s" % (np.pi / T))

    def line(tag, num, den):
        wc, gm, wg, kg, *_ = czl.zmargins(num, den, T)
        s1 = ("ω_c = " + ", ".join("%.4g" % x for x in wc)) if wc.size else "无 0 dB 交点"
        s2 = ("γ = " + ", ".join("%.2f°" % x for x in gm)) if gm.size else "γ = —"
        out = ["%-6s %-30s %s" % (tag, s1, s2)]
        if wg.size:
            out.append("%-6s ω_g = %s   K_g = %s" % (
                tag, ", ".join("%.4g" % x for x in wg[:3]),
                ", ".join("%.2f dB" % x for x in kg[:3])))
        else:
            out.append("%-6s 相位不穿越 -180°，K_g = ∞" % tag)
        return out

    L += line("校正前", d["g_num"], d["g_den"])
    if has_cmp:
        L += line("校正后", d["num"], d["den"])

    L.append("")
    L.append("【闭环时域（采样点 kT）】")
    L.append("稳态值 y(∞) = %.5f" % d["y_inf"])
    if d["stable"]:
        m = d["met"]
        if m:
            if m.get("sigma") is not None:
                L.append("超调量 σ = %.2f%%" % m["sigma"])
            if m.get("tp") is not None and np.isfinite(m["tp"]):
                L.append("峰值 t_p = %.0f ms   (k = %d)"
                         % (m["tp"] * 1e3, round(m["tp"] / T)))
            else:
                L.append("峰值 t_p = —")
            if m.get("ts") is not None and np.isfinite(m["ts"]):
                L.append("调节 t_s(2%%) = %.0f ms   (k = %d)"
                         % (m["ts"] * 1e3, round(m["ts"] / T)))
            else:
                L.append("调节 t_s(2%%) = —（未进入 ±2% 或为极限环）")
        if d["zeta"] is not None:
            L.append("主导极点 z = %.4f%+.4fj  →  ζ = %.3f, ω_n = %.3f"
                     % (d["zdom"].real, d["zdom"].imag, d["zeta"], d["wn"]))
    else:
        L.append("⚠ 闭环不稳定：max|z| = %.4f > 1" % np.max(np.abs(d["roots_cl"])))
        L.append("   阶跃响应发散，σ / t_p / t_s 无意义")

    L.append("")
    L.append("【极点零点（校正后开环）】")
    def _zf(q):
        q = complex(q)
        return ("%.4f%+.4fj" % (q.real, q.imag)) if abs(q.imag) > 1e-9 else ("%.4f" % q.real)

    L.append("开环极点：" + ", ".join(_zf(q) for q in d["poles_ol"]))
    if d["zeros_ol"].size:
        L.append("开环零点：" + ", ".join(_zf(q) for q in d["zeros_ol"]))
    L.append("闭环极点：" + ", ".join(_zf(q) for q in d["roots_cl"]))
    L.append("")
    L.append("闭环稳定 ✔" if d["stable"] else "闭环不稳定 ✘")
    return "\n".join(L)


def draw(fig, d, has_cmp, gc_label):
    fig.clear()
    gs = fig.add_gridspec(2, 2, hspace=0.42, wspace=0.28,
                          left=0.07, right=0.97, top=0.90, bottom=0.08)
    A = fig.add_subplot(gs[0, 0])
    B = fig.add_subplot(gs[0, 1], sharex=A)
    Cc = fig.add_subplot(gs[1, 0])
    D = fig.add_subplot(gs[1, 1])

    w = d["w"]
    r_raw, r_cmp = d["res"]["raw"], d["res"]["cmp"]
    c_raw, c_cmp = "#7a8fa6", "#c0392b"

    # (a) 幅频
    A.semilogx(w, r_raw["mag"], color=c_raw, lw=1.6, label="校正前 $G_0$")
    if has_cmp:
        A.semilogx(w, r_cmp["mag"], color=c_cmp, lw=1.9, label="校正后 $G_cG_0$")
    A.axhline(0, color="k", lw=0.9)
    for r, col in ((r_raw, c_raw), (r_cmp, c_cmp)):
        for x in r["wc"][:1]:
            A.plot([x], [0], "o", ms=6, color=col, zorder=5)
            A.axvline(x, color=col, lw=0.6, ls=":", zorder=1)
    if has_cmp and len(r_raw["wc"]) and len(r_cmp["wc"]):
        A.text(0.02, 0.04, "$\\omega_c$: %.3f → %.3f rad/s  (%+.1f%%)"
               % (r_raw["wc"][0], r_cmp["wc"][0],
                  100 * (r_cmp["wc"][0] / r_raw["wc"][0] - 1)),
               transform=A.transAxes, fontsize=7.4, color="#334155")
    elif len(r_raw["wc"]):
        A.text(0.02, 0.04, "$\\omega_c$ = %.3f rad/s" % r_raw["wc"][0],
               transform=A.transAxes, fontsize=7.4, color="#334155")
    A.set_ylabel(r"$20\lg|G|$  (dB)")
    A.set_title("(a) 幅频", fontsize=9.8)
    A.grid(alpha=0.18, which="both")
    A.legend(fontsize=7.8, loc="best")

    # (b) 相频
    B.semilogx(w, r_raw["ph"], color=c_raw, lw=1.6, label="校正前")
    if has_cmp:
        B.semilogx(w, r_cmp["ph"], color=c_cmp, lw=1.9, label="校正后")
    B.axhline(-180, color="k", lw=0.8, ls="--", alpha=0.6)
    ph_all = np.concatenate([r_raw["ph"], r_cmp["ph"]])
    B.set_ylim(min(-185.0, float(ph_all.min()) - 4), float(ph_all.max()) + 8)
    for r, col, off, ha in ((r_raw, c_raw, (-9, -14), "right"),
                            (r_cmp, c_cmp, (-12, 14), "right")):
        if not has_cmp and col == c_cmp:
            continue
        if not len(r["wc"]):
            continue
        x = r["wc"][0]
        y = float(np.interp(np.log10(x), np.log10(w), r["ph"]))
        B.plot([x], [y], "o", ms=6, color=col, zorder=5)
        B.annotate("$\\varphi$=%.3f$^\\circ$  $\\gamma$=%.3f$^\\circ$"
                   % (y, 180 + y), xy=(x, y), xytext=off,
                   textcoords="offset points", fontsize=7.4, color=col, ha=ha)
        for xg in r["wg"][:1]:
            yg = float(np.interp(np.log10(xg), np.log10(w), r["ph"]))
            B.plot([xg], [yg], "s", ms=4.5, mfc="none", color=col, zorder=5)
            Lg = float(np.interp(np.log10(xg), np.log10(w), r["mag"]))
            B.annotate("$\\omega_g$=%.3f  $L_g$=%+.3f dB" % (xg, Lg),
                       xy=(xg, yg), xytext=(-8, 12), textcoords="offset points",
                       fontsize=7.2, color=col, ha="right")
    B.set_ylabel(r"$\angle G$  (deg)")
    B.set_title("(b) 相频", fontsize=9.8)
    B.grid(alpha=0.18, which="both")
    B.legend(fontsize=7.8, loc="best")

    # (c) 阶跃
    _nl = d.get("nl") or "none"
    Cc.plot(d["t"], d.get("r", 1.0), color="0.55", lw=1.2, ls="--",
            label="输入 $r(t)$")
    Cc.plot(d["t"], d["y"], color=c_cmp, lw=1.9, label="输出 $c(t)$")
    Cc.legend(fontsize=7.4, loc="lower right")
    _y = np.asarray(d["y"], dtype=float)
    try:
        _met = d.get("met") or {}
        _tp, _ts = _met.get("tp"), _met.get("ts")
        _top = float(max(1.0, _y.max()))
        if _tp and np.isfinite(_tp) and (_met.get("sigma") or 0) > 0.1:
            Cc.axvline(_tp, color=c_cmp, lw=0.8, ls=":", alpha=0.85)
            Cc.annotate("$t_p$=%.3f s" % _tp, xy=(_tp, _top * 1.02),
                        fontsize=7.2, color=c_cmp, ha="left", va="bottom")
        if _ts and np.isfinite(_ts):
            Cc.axvline(_ts, color="#2c8a3e", lw=0.8, ls="--", alpha=0.8)
            Cc.annotate("$t_s$(2%%)=%.3f s" % _ts, xy=(_ts, _top * 0.80),
                        xytext=(-4, 0), textcoords="offset points",
                        fontsize=7.2, color="#2c8a3e", ha="right", va="top")
    except Exception:
        pass
    Cc.set_ylim(float(min(0.0, _y.min())) - 0.02,
                float(max(1.0, _y.max())) * 1.12)   # 给峰值标注留出空间
    Cc.axhline(1, color="k", lw=0.8, ls=":")
    try:
        t, y = d["t"], d["y"]
        if d.get("kind", "step") != "step":
            raise RuntimeError("非阶跃输入不标峰值")
        ip = int(np.argmax(y))
        Cc.plot([t[ip]], [y[ip]], "o", ms=6, color=c_cmp, zorder=6)
        Cc.annotate("(%.3f s, %.3f)" % (t[ip], y[ip]),
                    xy=(t[ip], y[ip]), xytext=(8, 10),
                    textcoords="offset points", fontsize=7.2, color=c_cmp)
        _yinf = float(d.get("y_inf") or (y[-1] if len(y) else 1.0))
        Cc.axhline(_yinf, color="0.45", lw=0.7, ls="--")
        Cc.text(0.98, _yinf, "$y(\\infty)$=%.3f" % _yinf,
                transform=Cc.get_yaxis_transform(),
                fontsize=7.2, color="0.35", ha="right", va="bottom")
    except Exception:
        if d.get("kind", "step") != "step":
            Cc.annotate("末时刻误差 e=%.3f" % float(d.get("e_ss") or 0.0),
                        xy=(d["t"][-1], d["y"][-1]), xytext=(-8, -16),
                        textcoords="offset points", fontsize=7.6,
                        color="#c0392b", ha="right")
    if d["stable"]:
        Cc.axhspan(0.98, 1.02, color="0.88", alpha=0.8, zorder=0)
    Cc.set_xlabel("t  (s)")
    Cc.set_ylabel("c(t)")
    _tn = {"step": "单位阶跃", "ramp": "单位斜坡", "accel": "单位加速度"}[
        d.get("kind", "step")]
    _suffix = ""
    if _nl != "none":
        _suffix = "（非线性：" + (d.get("nl_desc") or cnl.NL_NAMES.get(_nl, _nl)) + "）"
        Cc.text(0.02, 0.06, "非线性时域仿真", transform=Cc.transAxes,
                fontsize=7.2, color="#8e44ad", va="bottom")
    Cc.set_title("(c) 闭环响应：" + _tn + _suffix, fontsize=9.8)
    Cc.grid(alpha=0.18)

    # (d) 零极点
    pts = np.concatenate([d["poles_ol"], d["zeros_ol"], d["roots_cl"]])
    pts = pts[np.isfinite(pts)]
    mags = np.abs(pts)
    lim = 1.25 * (mags.max() if mags.size else 1.0)
    D.axvspan(0, 0.35 * lim, color="#f9dede", zorder=0)
    if d["poles_ol"].size:
        D.plot(d["poles_ol"].real, d["poles_ol"].imag, "x", ms=9, mew=2.0,
               color="#c0392b", label="开环极点")
    if d["zeros_ol"].size:
        D.plot(d["zeros_ol"].real, d["zeros_ol"].imag, "o", ms=7, mfc="none",
               mec="#2c8a3e", mew=1.8, label="开环零点")
    D.plot(d["roots_cl"].real, d["roots_cl"].imag, "*", ms=12, color="#8e44ad",
           label="闭环极点")
    D.axhline(0, color="k", lw=0.7)
    D.axvline(0, color="k", lw=0.7)
    D.set_xlim(-lim, 0.35 * lim)
    D.set_ylim(-lim, lim)
    D.set_xlabel("Re")
    D.set_ylabel("Im")
    D.set_title("(d) 零极点分布", fontsize=9.8)
    D.grid(alpha=0.18)
    D.legend(fontsize=7.4, loc="upper left")

    fig.suptitle("校正前后对比    Gc = " + gc_label if has_cmp
                 else "分析原系统（无校正环节）", fontsize=10.5)


# ---------------------------------------------------------------- 界面
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("控制系统校正验算器  ·  ctrl_app")
        self.geometry("1280x820")
        self.minsize(980, 640)

        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        top = ttk.Frame(self, padding=(10, 8, 10, 4))
        top.pack(side="top", fill="x")

        ttk.Label(top, text="原开环  G0(s) =").grid(row=0, column=0, sticky="w")
        self.e_g0 = ttk.Entry(top, width=58)
        self.e_g0.grid(row=0, column=1, padx=6, pady=3, sticky="we")

        ttk.Label(top, text="校正环节  Gc(s) =").grid(row=1, column=0, sticky="w")
        self.e_gc = ttk.Entry(top, width=58)
        self.e_gc.grid(row=1, column=1, padx=6, pady=3, sticky="we")

        ttk.Label(top, text="采样周期  T =").grid(row=2, column=0, sticky="w")
        self.e_T = ttk.Entry(top, width=12)
        self.e_T.grid(row=2, column=1, padx=6, pady=3, sticky="w")

        self.btn_run = ttk.Button(top, text="分析 (Enter)", command=self.on_run)
        self.btn_run.grid(row=0, column=2, padx=4, sticky="we")
        ttk.Button(top, text="保存图…", command=self.on_save).grid(
            row=1, column=2, padx=4, sticky="we")

        self.cb = ttk.Combobox(top, values=list(PRESETS), state="readonly", width=30)
        self.cb.grid(row=0, column=3, padx=(10, 4), sticky="we")
        self.cb.set(list(PRESETS)[0])
        self.cb.bind("<<ComboboxSelected>>", self.on_preset)
        ttk.Button(top, text="复制指标", command=self.on_copy).grid(
            row=1, column=3, padx=(10, 4), sticky="we")
        self.lbl_mode = ttk.Label(top, text="连续系统", foreground="#1f6fb4")
        self.lbl_mode.grid(row=2, column=3, padx=(10, 4), sticky="w")
        self.var_rl = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="第 (d) 图画根轨迹", variable=self.var_rl,
                        command=self._redraw_only).grid(row=2, column=2,
                                                        padx=4, sticky="w")

        top.columnconfigure(1, weight=1)

        hint = ttk.Label(
            top,
            text="支持普通表达式（2s+1、(s/12.12+1)、s^2）与 LaTeX（\\frac{a}{b}）；"
                 "留空 Gc 表示只看原系统；填了采样周期 T 就走离散（G0 经零阶保持采样，"
                 "Gc 可写 z 也可写 s）。",
            foreground="#555")
        hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=6)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=4)
        body.add(right, weight=1)
        self.body = body

        self.fig = Figure(figsize=(7.6, 5.8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=left)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("resize_event", self._on_canvas_resize)
        self._in_resize = False
        self.toolbar = NavigationToolbar2Tk(self.canvas, left, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="bottom", fill="x")

        self.txt = tk.Text(right, width=44, wrap="word", font=("Consolas", 9))
        sb = ttk.Scrollbar(right, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)

        self.status = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status, anchor="w",
                  relief="sunken", padding=(6, 3)).pack(side="bottom", fill="x")
        self.after(150, self._fix_sash)

        self.bind("<Return>", lambda e: self.on_run())
        self._data = None
        self._gc_label = ""

    # -------------------------------------------------- 事件
    def _on_canvas_resize(self, event):
        """让 Figure 跟着画布尺寸走，避免图比控件宽、被裁掉右半边。"""
        if self._in_resize or event.width < 50 or event.height < 50:
            return
        self._in_resize = True
        try:
            dpi = self.fig.dpi
            w, h = event.width / dpi, event.height / dpi
            cw, ch = self.fig.get_size_inches()
            if abs(w - cw) > 0.05 or abs(h - ch) > 0.05:
                self.fig.set_size_inches(w, h, forward=True)
        except Exception:
            pass
        finally:
            self._in_resize = False

    def _fix_sash(self):
        """PanedWindow 首次布局时会把宽度全给左栏，手动把分隔条拉到右边。"""
        try:
            self.update_idletasks()
            w = self.body.winfo_width()
            if w > 300:
                self.body.sashpos(0, int(w * 0.66))
        except Exception:
            pass

    def on_preset(self, _evt=None):
        item = PRESETS[self.cb.get()]
        g0, gc = item[0], item[1]
        T = item[2] if len(item) > 2 else ""
        self.e_g0.delete(0, "end")
        self.e_g0.insert(0, g0)
        self.e_gc.delete(0, "end")
        self.e_gc.insert(0, gc)
        self.e_T.delete(0, "end")
        self.e_T.insert(0, T)
        self.on_run()

    def on_run(self):
        g0 = self.e_g0.get().strip()
        gc = self.e_gc.get().strip()
        Ts = self.e_T.get().strip()
        if not g0:
            messagebox.showwarning("缺少输入", "请先填写原开环传递函数 G0(s)")
            return
        T = None
        if Ts:
            try:
                T = float(Ts)
            except ValueError:
                messagebox.showwarning("采样周期不合法", "T 要填一个正数，例如 0.1")
                return
            if T <= 0:
                messagebox.showwarning("采样周期不合法", "T 必须 > 0")
                return
        self.btn_run.configure(state="disabled")
        self.status.set("计算中…")
        self._gc_label = gc
        self._T = T
        self.lbl_mode.configure(
            text=("离散：T = %g s" % T) if T else "连续系统",
            foreground=("#b9770e" if T else "#1f6fb4"))

        def work():
            try:
                d = compute_z(g0, gc, T) if T else compute(g0, gc)
                self.after(0, lambda: self._show(d))
            except Exception:
                err = traceback.format_exc(limit=3)
                self.after(0, lambda: self._fail(err))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, d):
        self._data = d
        has_cmp = bool(self._gc_label)
        if getattr(self, "_T", None):
            czl.draw(self.fig, d, has_cmp)
            self.fig.suptitle(
                "离散系统   T = %g s%s" % (
                    self._T, ("   D = " + self._gc_label) if has_cmp else ""),
                fontsize=10.5, y=0.975)
        else:
            draw(self.fig, d, has_cmp, self._gc_label)
        self._maybe_rl()
        self.canvas.draw_idle()
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", metrics_text_z(d, has_cmp)
                        if getattr(self, "_T", None) else metrics_text(d, has_cmp))
        self.btn_run.configure(state="normal")
        self.status.set("完成" + ("" if d["stable"] else "   ⚠ 闭环不稳定"))

    def _maybe_rl(self):
        """把第 (d) 个子图换成根轨迹"""
        if not getattr(self, "var_rl", None) or not self.var_rl.get():
            return
        d = self._data
        if not d:
            return
        try:
            ax = self.fig.axes[-1]
            ax.clear()
            crl.draw(ax, d["num"], d["den"],
                     discrete=bool(getattr(self, "_T", None)),
                     T=getattr(self, "_T", None) or 1.0, k_mark=1.0)
        except Exception:
            traceback.print_exc()

    def _redraw_only(self):
        if self._data is not None:
            self._show(self._data)

    def _fail(self, err):
        self.btn_run.configure(state="normal")
        self.status.set("出错")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", "解析/计算失败：\n\n" + err)
        messagebox.showerror("出错了", "表达式解析或计算失败，详见右侧信息栏。\n\n"
                                       + err.strip().splitlines()[-1])

    def on_save(self):
        if self._data is None:
            messagebox.showinfo("提示", "请先点“分析”生成图。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG 图片", "*.png"),
                                                ("PDF", "*.pdf"),
                                                ("SVG", "*.svg")],
            initialfile="ctrl_check.png")
        if not path:
            return
        self.fig.savefig(path, bbox_inches="tight", facecolor="white")
        self.status.set("已保存：" + path)

    def on_copy(self):
        if not self.txt.get("1.0", "end").strip():
            return
        self.clipboard_clear()
        self.clipboard_append(self.txt.get("1.0", "end").strip())
        self.status.set("指标已复制到剪贴板")


def _selftest():
    """打包自检：python ctrl_app.py --selftest 或 环境变量 CTRLCHECK_SELFTEST=1"""
    import os, sys as _s
    here = os.path.dirname(os.path.abspath(_s.argv[0]))
    log = os.path.join(here, "selftest.txt")
    with open(log, "w", encoding="utf-8") as f:
        try:
            d = compute("100*(0.1s+1)/((s+1)*(0.2s+1)*(0.02s+1))",
                        "(s/12.12+1)/(s/70.34+1)")
            f.write("CONTINUOUS OK\n" + metrics_text(d, True))
            dz = compute_z("10/(s*(s+1))", "(z-0.8)/(z-0.3)", 0.1)
            f.write("\n\nDISCRETE OK\n" + metrics_text_z(dz, True))
        except Exception:
            f.write("FAIL\n" + traceback.format_exc())


if __name__ == "__main__":
    import os, sys as _s
    if "--selftest" in _s.argv or os.environ.get("CTRLCHECK_SELFTEST"):
        _selftest()
        raise SystemExit(0)
    App().mainloop()



def nichols(num, den, w=None):
    """闭环幅相特性 + 四大闭环指标：M(0)、Mr、Wr、Wb（以及穿越/带宽）"""
    if w is None:
        w = np.logspace(-3, 4, 3000)
    G = np.polyval(np.asarray(num, float), 1j * w) / np.polyval(np.asarray(den, float), 1j * w)
    T = G / (1.0 + G)
    M = np.abs(T)
    M0 = float(M[0])
    band = M0 / np.sqrt(2.0) if M0 > 0 else 0.0
    idx = np.where(M < band)[0]
    Wb = float(w[idx[0]]) if idx.size else float("nan")
    Mr = float(M.max())
    Wr = float(w[int(M.argmax())]) if Mr > M0 * 1.0005 else 0.0
    return {"w": w, "G": G, "M": M,
            "phT": np.degrees(np.unwrap(np.angle(T))),
            "M0": M0, "Mr": Mr, "Wr": Wr, "Wb": Wb, "band": band}


def draw_nichols(fig, d):
    """两联：Nichols 图（开环）+ 闭环幅频 M(w)"""
    ax = fig.add_subplot(1, 2, 1)
    L = 20 * np.log10(np.maximum(np.abs(d["G"]), 1e-12))
    ph = np.degrees(np.unwrap(np.angle(d["G"])))
    ax.plot(ph, L, color="#1f6fb4", lw=1.6)
    ax.axhline(0, color="k", lw=0.7)
    ax.axvline(-180, color="k", lw=0.7, ls="--")
    ax.plot([-180], [0], "x", ms=9, mew=2, color="#c0392b")
    ax.set_xlabel("$\\angle G$ (deg)"); ax.set_ylabel("$20\\lg|G|$ (dB)")
    ax.set_title("(a) Nichols 图", fontsize=9.8)
    ax.grid(alpha=0.25, lw=0.5)

    ax2 = fig.add_subplot(1, 2, 2)
    ax2.semilogx(d["w"], d["M"], color="#8e44ad", lw=1.8)
    ax2.axhline(d["M0"], color="0.5", lw=0.8, ls=":")
    ax2.axhline(d["band"], color="#2c8a3e", lw=0.8, ls="--")
    if d["Mr"] > d["M0"] * 1.0005:
        ax2.plot([d["Wr"]], [d["Mr"]], "o", ms=6, color="#c0392b")
    if d["Wb"] == d["Wb"]:
        ax2.axvline(d["Wb"], color="#2c8a3e", lw=1.0, ls="-.")
    ax2.set_xlabel("$\\omega$ (rad/s)"); ax2.set_ylabel("$|T(j\\omega)|$")
    ax2.set_title("(b) 闭环幅频", fontsize=9.8)
    ax2.grid(alpha=0.25, lw=0.5, which="both")
    return ax, ax2
