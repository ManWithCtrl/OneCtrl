# -*- coding: utf-8 -*-
"""
控制校正验算器 · 网页版（手机 / 平板 / 电脑都能用）

用法：
    python ctrl_web.py              # 默认 0.0.0.0:8000，自动开浏览器
    python ctrl_web.py -p 8080      # 换端口
    python ctrl_web.py --no-open    # 不自动开浏览器

只依赖标准库 + numpy/matplotlib/sympy，不需要 flask。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import os
import socket
import sys
import threading
import traceback
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import matplotlib

matplotlib.use("Agg", force=True)

import numpy as np                             # noqa: E402
from matplotlib.figure import Figure           # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402

sys.path.insert(0, __file__.rsplit("\\", 1)[0] or ".")
import ctrl_app as A                           # noqa: E402
import ctrl_zcheck as czl                      # noqa: E402
import ctrl_rootlocus as crl                   # noqa: E402
import ctrl_classify as ccf                    # noqa: E402
import ctrl_check as cc
import ctrl_formula as cfx                        # noqa: E402
import ctrl_stability as cst                   # noqa: E402

_LOCK = threading.Lock()      # matplotlib 不是线程安全的

# 结果缓存：公式/参数完全相同的请求直接复用上一次的 JSON（内含 base64 图）
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 6

# --------------------------------------------------------------- 图表风格
_CHART_RC = {
    "figure.facecolor": "#ffffff",
    "axes.facecolor": "#ffffff",
    "axes.edgecolor": "#e4e9f0",
    "axes.linewidth": 0.9,
    "axes.grid": True,
    "grid.color": "#eef2f7",
    "grid.linewidth": 0.8,
    "font.size": 9.5,
    "axes.titlesize": 10.0,
    "axes.titleweight": "normal",
    "axes.titlecolor": "#334155",
    "axes.labelcolor": "#475569",
    "xtick.color": "#64748b",
    "ytick.color": "#64748b",
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.frameon": False,
    "legend.fontsize": 8.5,
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
                        "Noto Sans CJK JP", "WenQuanYi Zen Hei",
                        "Source Han Sans SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
}


def _apply_style():
    matplotlib.rcParams.update(_CHART_RC)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# 页面拆成 templates/index.html + static/*.css|js，改完刷新浏览器即可生效
# （每次请求都重新读盘，不用重启服务）
_MIME = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json; charset=utf-8",
}


def _read(path, fallback=None):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return fallback



ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
<rect width="192" height="192" rx="44" fill="#2563eb"/>
<text x="96" y="134" font-size="112" font-family="Segoe UI,DejaVu Sans,sans-serif"
      font-weight="700" fill="#ffffff" text-anchor="middle">&#8721;</text></svg>"""

MANIFEST = {
    "name": "控制校正验算器",
    "short_name": "校正验算",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#f7f8fa",
    "theme_color": "#2563eb",
    "icons": [{"src": "/icon.svg", "sizes": "any",
               "type": "image/svg+xml", "purpose": "any maskable"}],
}


_IMG_CACHE = {}
_IMG_ORDER = []


def _store_img(raw, ext="png"):
    """把图片字节放进内存缓存，返回可被浏览器直接打开的 URL。"""
    key = hashlib.md5(raw).hexdigest()[:16]
    full = key + "." + ext
    if full not in _IMG_CACHE:
        _IMG_CACHE[full] = raw
        _IMG_ORDER.append(full)
        while len(_IMG_ORDER) > 48:
            _IMG_CACHE.pop(_IMG_ORDER.pop(0), None)
    return "/img/" + full


def _fig_to_data_uri(fig, with_bytes=False):
    FigureCanvasAgg(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="#ffffff", dpi=130)
    raw = buf.getvalue()
    try:                                  # 转 WebP，体积约降 60%
        from PIL import Image
        im2 = Image.open(io.BytesIO(raw)).convert("RGB")
        w2 = io.BytesIO()
        im2.save(w2, "WEBP", quality=82, method=4)
        uri = "data:image/webp;base64," + base64.b64encode(w2.getvalue()).decode()
    except Exception:
        uri = "data:image/png;base64," + base64.b64encode(raw).decode()
    return (uri, raw) if with_bytes else uri


def _num(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _json_safe(o):
    """JSON 不允许 NaN / Infinity（浏览器 JSON.parse 会直接报错），统一转 null。"""
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, (float, np.floating)):
        v = float(o)
        return v if np.isfinite(v) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _tiles(d, has_cmp, discrete):
    """把结果整理成“指标卡”数据，前端只负责画。"""
    raw, cmp_ = d["res"]["raw"], d["res"]["cmp"]

    def wc(r):
        return float(r["wc"][0]) if r["wc"].size else None

    def gm(r):
        return float(r["gm"][0]) if r["gm"].size else None

    w0, w1 = wc(raw), wc(cmp_)
    g0, g1 = gm(raw), gm(cmp_)

    met = d["met"] if (d["stable"] and d["met"]) else {}
    dp = d["dp"]
    nl_on = d.get("nl", "none") not in ("", "none")
    zeta = None if nl_on else (dp[0] if dp else None)

    ts_ms = met.get("ts", None)
    if ts_ms is not None:
        ts_ms *= 1000.0

    T = [
        dict(label="截止频率 ω<sub>c</sub>", unit=" rad/s", before=w0, after=w1 if has_cmp else w0,
             delta=(w1 - w0) if (has_cmp and w0 and w1) else None, good=None, hasCmp=has_cmp),
        dict(label="相角裕度 γ", unit="°", before=g0, after=g1 if has_cmp else g0,
             delta=(g1 - g0) if (has_cmp and g0 is not None and g1 is not None) else None,
             good="up", hasCmp=has_cmp),
        dict(label="超调量 σ", unit="%", before=None,
             after=_num(met.get("sigma")), delta=None, good="down", hasCmp=False),
        dict(label="调节时间 t<sub>s</sub>(2%)", unit=" ms", before=None,
             after=_num(ts_ms), delta=None, good="down", hasCmp=False),
        dict(label="主导阻尼比 ζ", unit="", before=None,
             after=_num(zeta), delta=None, good="up", hasCmp=False),
        dict(label="稳态误差 e<sub>ss</sub>", unit="%", before=None,
             after=_num(100.0 * d["e_ss"]) if np.isfinite(d["e_ss"]) else None,
             delta=None, good="down", hasCmp=False),
    ]
    return T


def _tiles_z(d, has_cmp):
    """离散版的指标卡（没有 res['raw']，要现算 G(z) 与 L(z) 的裕度）"""
    T = d["T"]

    def marg(n, dd):
        wc, gm, wg, kg, *_ = czl.zmargins(n, dd, T)
        return (float(wc[0]) if wc.size else None,
                float(gm[0]) if gm.size else None)

    w0, g0 = marg(d["g_num"], d["g_den"])
    if has_cmp:
        w1, g1 = marg(d["num"], d["den"])
    else:
        w1, g1 = w0, g0

    met = d["met"] if (d["stable"] and d["met"]) else {}
    ts_ms = met.get("ts")
    if ts_ms is not None:
        ts_ms *= 1000.0
    e_ss = None
    try:
        e_ss = 100.0 * max(0.0, 1.0 - float(d["y_inf"]))
    except Exception:
        pass

    return [
        dict(label="截止频率 ω<sub>c</sub>", unit=" rad/s", before=w0, after=w1 if has_cmp else w0,
             delta=(w1 - w0) if (has_cmp and w0 and w1) else None, good=None, hasCmp=has_cmp),
        dict(label="相角裕度 γ", unit="°", before=g0, after=g1 if has_cmp else g0,
             delta=(g1 - g0) if (has_cmp and g0 is not None and g1 is not None) else None,
             good="up", hasCmp=has_cmp),
        dict(label="超调量 σ", unit="%", before=None, after=_num(met.get("sigma")),
             delta=None, good="down", hasCmp=False),
        dict(label="调节时间 t<sub>s</sub>(2%)", unit=" ms", before=None, after=_num(ts_ms),
             delta=None, good="down", hasCmp=False),
        dict(label="主导阻尼比 ζ", unit="", before=None, after=_num(d.get("zeta")),
             delta=None, good="up", hasCmp=False),
        dict(label="稳态误差 e<sub>ss</sub>", unit="%", before=None, after=_num(e_ss),
             delta=None, good="down", hasCmp=False),
    ]


def _stats_extra(d, has_cmp):
    """文字版补充信息（KG 等），放进详细数据里用。"""
    raw, cmp_ = d["res"]["raw"], d["res"]["cmp"]
    out = []
    if raw["wg"].size:
        out.append("校正前 ω_g = %.4g rad/s，K_g = %.2f dB"
                   % (float(raw["wg"][0]), float(raw["kg"][0])))
    else:
        out.append("校正前 相位不穿越 −180°，K_g = ∞")
    if has_cmp:
        if cmp_["wg"].size:
            out.append("校正后 ω_g = %.4g rad/s，K_g = %.2f dB"
                       % (float(cmp_["wg"][0]), float(cmp_["kg"][0])))
        else:
            out.append("校正后 相位不穿越 −180°，K_g = ∞")
    return out



def _draw_poles(ax, roots, discrete=False):
    """第 (d) 面板：闭环极点图"""
    from matplotlib.patches import Rectangle, Circle
    r = np.asarray(roots, dtype=complex)
    if discrete:
        ax.add_patch(Circle((0, 0), 1.0, fill=False, ls="--", lw=1.0, color="0.55"))
        lim = 1.3
        out = int(np.sum(np.abs(r) > 1.0))
        lab = "单位圆外"
    else:
        m = max(1.0, float(np.max(np.abs(r))) if r.size else 1.0)
        lim = 1.25 * m
        ax.add_patch(Rectangle((0, -lim), lim, 2 * lim, facecolor="#fdecea",
                               edgecolor="none", zorder=0))
        out = int(np.sum(r.real > 1e-9))
        lab = "右半平面"
    ax.axhline(0, color="k", lw=0.6)
    ax.axvline(0, color="k", lw=0.6)
    good = (np.abs(r) < 1.0) if discrete else (r.real < 0)
    if np.any(good):
        ax.plot(r.real[good], r.imag[good], "o", ms=8, mfc="#1f6fb4",
                mec="white", mew=1.2)
    if np.any(~good):
        ax.plot(r.real[~good], r.imag[~good], "o", ms=8, mfc="#d1372c",
                mec="white", mew=1.2)
    ax.set_title("闭环极点：%d 个，%s %d 个" % (r.size, lab, out), fontsize=9.2,
                 color="#243447")
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.grid(alpha=0.25, lw=0.5)


def _draw_portrait(ax, num_arr, den_arr, discrete=False):
    """第 (d) 面板：相轨迹（仅连续二阶）"""
    ch = np.asarray(den_arr, dtype=float).copy()
    n = np.asarray(num_arr, dtype=float)
    ch[-len(n):] += n
    if discrete or ch.size != 3:
        ax.axis("off")
        ax.text(0.5, 0.55, "相轨迹只对【连续二阶】系统绘制", ha="center",
                fontsize=9.2, color="0.45")
        return
    a1, a2 = ch[1] / ch[0], ch[2] / ch[0]
    A = np.array([[0.0, 1.0], [-a2, -a1]])
    for path in cst.phase_portrait(A, xlim=(-3, 3), ylim=(-3, 3), n=11, tmax=10.0):
        if len(path) > 3:
            ax.plot(path[:, 0], path[:, 1], color="#1f6fb4", lw=0.8, alpha=0.75)
    ax.plot([0], [0], "x", ms=7, color="#c0392b")
    ax.set_title("相轨迹（闭环等效二阶）", fontsize=9.2, color="#243447")
    ax.set_xlabel("$x_1$", fontsize=8.5)
    ax.set_ylabel("$x_2$", fontsize=8.5)
    ax.grid(alpha=0.25, lw=0.5)



def _split_panels(fig, png_bytes=None, width=760):
    """把四联图按 axes 裁成单张图（手机端用）。重新按画布尺寸存一份，坐标才对得上。"""
    try:
        from PIL import Image
    except Exception:
        return []
    try:
        FigureCanvasAgg(fig)
        if png_bytes:
            im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        else:
            buf = io.BytesIO()
            fig.savefig(buf, format="png", facecolor="#ffffff", dpi=130)
            im = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
        W, H = im.size
        scale = 130.0 / float(fig.dpi)
        r = fig.canvas.get_renderer()
        out = []
        _boxes = []
        for ax in fig.axes:
            bb = ax.get_tightbbox(r)
            _boxes.append(((bb.x1 - bb.x0) * (bb.y1 - bb.y0), bb))
        _boxes.sort(key=lambda t: -t[0])
        _keep, _axes = [], []
        for _a, bb in _boxes:
            cx, cy = (bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2
            if any(abs(cx - k[0]) < 30 and abs(cy - k[1]) < 30 for k in _keep):
                continue
            _keep.append((cx, cy))
            _axes.append(bb)
        for bb in _axes:
            x0 = int(bb.x0 * scale) - 12
            x1 = int(bb.x1 * scale) + 12
            y0 = int(H - bb.y1 * scale) - 12
            y1 = int(H - bb.y0 * scale) + 12
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            if x1 - x0 < 60 or y1 - y0 < 60:
                continue
            crop = im.crop((x0, y0, x1, y1))
            crop = crop.resize((width, int(crop.height * width / crop.width)),
                               Image.LANCZOS)
            b = io.BytesIO()
            mime = "image/png"
            try:                       # WebP 体积约为 PNG 的 35%~45%
                crop.save(b, "WEBP", quality=80, method=4)
                mime = "image/webp"
            except Exception:
                b = io.BytesIO()
                crop.save(b, "WEBP", quality=80, method=4)
            raw_img = b.getvalue()
            ext = "webp" if mime == "image/webp" else "png"
            out.append({"u": _store_img(raw_img, ext),
                        "d": "data:%s;base64," % mime +
                             base64.b64encode(raw_img).decode()})
        return out
    except Exception:
        traceback.print_exc()
        return []


def _df_lines(df) -> list:
    """描述函数法的结论：N(A) 公式、交点幅值、频率、周期。"""
    out = []
    kind = (df or {}).get("kind")
    formula = {
        "relay": "4M/(πA)",
        "relay_dz": "4M/(πA)·√(1−(a/A)²)（A>a）",
        "relay_hyst": "4M/(πA)·[√(1−(a/A)²) − j·(a/A)]（A>a，复值）",
        "sat": "(2/π)[asin(a/A)+(a/A)√(1−(a/A)²)]（A≥a，A<a 时 N=1）",
    }.get(kind)
    if formula:
        out.append("描述函数：N(A) = %s" % formula)
    if kind == "relay_hyst":
        out.append("描述函数：−1/N(A) 为 Im = −πa/(4M) 的水平射线，"
                   "交点取 G(jω) 与该水平线的穿越点")
    cyc = (df or {}).get("cycles") or []
    if cyc:
        for c in cyc[:3]:
            per = ("，周期 %.3g s" % c["period"]) if c.get("period") else ""
            if kind == "relay_hyst":
                verdict = ""
                if c.get("stable") is not None:
                    verdict = ("，仿真判定：%s"
                               % ("稳定自振" if c["stable"] else "不稳定（不会持续）"))
                out.append("描述函数：交点 A = %.4g，ω = %.4g rad/s%s，"
                           "G(jω) = %.4g %+.4gj%s"
                           % (c["A"], c["w"], per,
                              c["G"].real, c["G"].imag, verdict))
            else:
                out.append("描述函数：交点 A = %.4g，ω = %.4g rad/s%s"
                           " → 可能自振（N(A)=%.4g）"
                           % (c["A"], c["w"], per, c["N"]))
    else:
        out.append("描述函数：−1/N(A) 与 G(jω) 无交点 → 无自振")
    return out


def _df_payload(df) -> dict | None:
    """描述函数结果的前端摘要（JSON 友好）。"""
    if not df:
        return None
    return {
        "kind": df.get("kind"),
        "M": float(df.get("M", 1.0)),
        "a": float(df.get("a", 1.0)),
        "cycles": [{"A": float(c["A"]), "w": float(c["w"]),
                    "N": float(np.real(c["N"])),
                    "gRe": float(c["G"].real), "gIm": float(c["G"].imag),
                    "stable": c.get("stable"),
                    "period": (float(c["period"]) if c.get("period") else None)}
                   for c in (df.get("cycles") or [])],
    }


def _stab_text(st: dict, discrete: bool, nl: str = "none") -> list:
    """把稳定性判据结果整理成几行自然语言"""
    out = []
    if discrete:
        jr = st["jury"]; uc = st["uc"]
        out.append("Jury：%s" % ("全部条件满足" if jr["stable"] else "存在不满足条件"))
        for name, ok, info in jr["conds"]:
            out.append("　%s %s（%s）" % ("√" if ok else "×", name, info))
        out.append("单位圆：max|z| = %.4f%s"
                   % (uc["rmax"],
                      "（恰在单位圆上 → 临界稳定）" if uc.get("marginal") else ""))
        if nl != "none" and st.get("df") is not None:
            out.extend(_df_lines(st["df"]))
    else:
        r = st["routh"]; nyq = st["nyq"]; bd = st["bode"]
        out.append("Routh：首列 %d 次变号 → %d 个右半平面根%s"
                   % (r["changes"], r["changes"],
                      "（首列出现零：有根在虚轴/原点）"
                      if r.get("marginal") else ""))
        if nyq.get("marginal"):
            out.append("Nyquist：N = %d, P = %d，曲线穿过 (−1,j0) → 闭环临界稳定"
                       "（Z 不能按圈数取整）" % (nyq["N"], nyq["P"]))
        else:
            out.append("Nyquist：N = %d（顺时针包围 −1）, P = %d → Z = P + N = %d"
                       % (nyq["N"], nyq["P"], nyq["Z"]))
        if bd["wc"]:
            _seen = []
            for _x in bd["wc"][:3]:
                _s = "%.4g" % _x
                if _s not in _seen:
                    _seen.append(_s)
            out.append("Bode：截止频率 ω_c = %s rad/s" % "、".join(_seen))
        den_arr = np.asarray(st.get("den", []), float)
        if den_arr.size and abs(den_arr[-1]) < 1e-9 * max(1.0, float(np.max(np.abs(den_arr)))):
            out.append("Nyquist：含积分环节，已补画右侧无穷半圆")
        if nl != "none" and st.get("df") is not None:
            out.extend(_df_lines(st["df"]))
        if bd["wg"]:
            out.append("Bode：相位穿越 ω_g = %s rad/s，L_g = %s dB"
                       % ("、".join("%.4g" % x for x in bd["wg"][:3]),
                          "、".join("%.3g" % x for x in bd["Lg"][:3])))
    return out



# ---------------- 轻量防护：长度 / 阶次 / 频次 ----------------
MAXLEN = 300          # 单个表达式最长字符数
MAXDEG = 40           # 分子分母最高阶
_RATE = {}            # ip -> [时间戳]
RATE_N, RATE_WIN = 40, 60.0   # 每 IP 每 60 秒最多 40 次


def _check_input(g0: str, gc: str):
    if len(g0) > MAXLEN or len(gc) > MAXLEN:
        raise ValueError("表达式太长（上限 %d 字符）" % MAXLEN)
    for t in (g0, gc):
        # 去掉小数部分再查连续四位数字，避免误伤 0.03349 这类正常系数
        if re.search(r"\d{4,}", re.sub(r"\.\d+", "", t)):   # 1e1000、999999 这类
            raise ValueError("存在过长的数字，疑似恶意输入")
    return True


def _rate_ok(ip: str) -> bool:
    import time
    now = time.time()
    q = [t for t in _RATE.get(ip, []) if now - t < RATE_WIN]
    if len(q) >= RATE_N:
        _RATE[ip] = q
        return False
    q.append(now)
    _RATE[ip] = q
    return True


def _friendly(e):
    """把异常翻成中文 + 一条建议（每条不超过 40 字）"""
    t = str(e)
    rules = [
        ("还有别的符号", "这一栏只认一个变量。建议：z 写到 Gc 栏，或填采样周期 T"),
        ("括号不配对", "括号数量对不上。建议：检查相邻括号如 (z-1)(z-e^(-1))"),
        ("必须是真分式", "分子阶次 >= 分母。建议：给 G0 补一个极点，或 Gc 写成分式"),
        ("PolynomialError", "出现非多项式运算（如 s 的指数）。建议：改写成分式乘积"),
        ("非有理", "含时滞或非有理项。建议：用 Padé 近似 (1-0.05s)/(1+0.05s)"),
        ("采样周期", "T 必须是正数。建议：填 0.1 这样的正数"),
        ("syms", "表达式无法解析。建议：检查乘号与括号是否写全"),
        ("TokenError", "括号或运算符号不完整。建议：补齐右括号后重试"),
        ("division by zero", "分母在当前点为零。建议：检查是否漏写 s"),
    ]
    for k, msg in rules:
        if k in t:
            return "⚠ " + msg
    m = t.strip()
    return "⚠ " + (m[:60] + "…" if len(m) > 60 else m)


def analyse(req: dict) -> dict:
    g0 = (req.get("g0") or "").strip()
    gc = (req.get("gc") or "").strip()
    T = (req.get("T") or "").strip()
    panel = (req.get("panel") or "rl").strip()
    nl = (req.get("nl") or "none").strip()
    try:
        nz = float(req.get("nz", 1.0))
    except Exception:
        nz = 1.0
    nz = min(10.0, max(0.1, nz))
    _check_input(g0, gc)
    kind = (req.get("kind") or "step").strip()
    try: _w = int(float(req.get("w") or 0))
    except Exception: _w = 0
    narrow = 0 < _w < 620
    try: nlM = float(req.get("nlM") or 1.0)
    except Exception: nlM = 1.0
    try: nla = float(req.get("nla") or 1.0)
    except Exception: nla = 1.0
    if not g0:
        raise ValueError("G₀ 不能为空")
    has_cmp = bool(gc)
    domainNote = ""

    with _LOCK:
        _apply_style()
        if T:
            Tv = float(T)
            if Tv <= 0:
                raise ValueError("采样周期 T 必须大于 0")
            d = A.compute_z(g0, gc, Tv, kind=kind, nl=nl, M=nlM, a=nla)
            fig = Figure(figsize=(10.2, 7.4), dpi=110)
            czl.draw(fig, d, has_cmp)
            fig.suptitle("离散系统   T = %g s%s" % (
                Tv, ("   D = " + gc) if has_cmp else ""), fontsize=10.5, y=0.985)
            text = A.metrics_text_z(d, has_cmp)
            mode = "离散 · T = %g s" % Tv
            if nl != "none":
                mode += " · 非线性 " + (d.get("nl_desc") or nl)
            if d.get("note"):
                mode += " · " + d["note"]
            discrete = True
            try:
                dom, domainNote = ccf.detect_domain(g0, gc, T)
            except Exception:
                pass
        else:
            d = A.compute(g0, gc, kind, nl=nl, M=nlM, a=nla)
            fig = Figure(figsize=(10.2, 7.4), dpi=110)
            A.draw(fig, d, has_cmp, gc)
            text = A.metrics_text(d, has_cmp)
            mode = "连续"
            if nl != "none":
                mode += " · 非线性 " + (d.get("nl_desc") or nl)
            discrete = False
            Tv = 1.0
            try:
                dom, domainNote = ccf.detect_domain(g0, gc, T)
            except Exception:
                pass

        # 第 (d) 面板：根轨迹 / 闭环极点 / 相轨迹
        try:
            ax = fig.axes[-1]
            ax.clear()
            if panel == "poles":
                _draw_poles(ax, d["roots_cl"], discrete=discrete)
            elif panel == "portrait":
                _draw_portrait(ax, d["num"], d["den"], discrete=discrete)
            else:
                crl.draw(ax, d["num"], d["den"], discrete=discrete, T=Tv, k_mark=1.0)
        except Exception:
            traceback.print_exc()

        uri, _raw = _fig_to_data_uri(fig, with_bytes=True)
        _img_url = _store_img(_raw, "png")
        _imgs = _split_panels(fig, _raw) if narrow else []
        if narrow and _imgs:
            uri = ""          # 手机端只回单图，省掉整图传输

        # 校正环节识别（针对 Gc 本身，而不是整环）
        comp = []
        if has_cmp:
            try:
                cn, cd = cc.to_numden(gc)
                comp = ccf.report(ccf.analyse(np.asarray(cn, float),
                                              np.asarray(cd, float), discrete=False))
            except Exception:
                try:
                    if discrete:
                        ex = czl._parse(gc, czl.z, "Gc")
                        cn, cd = czl._coeffs(ex, czl.z)
                        comp = ccf.report(ccf.analyse(np.asarray(cn, float),
                                                      np.asarray(cd, float), discrete=True))
                except Exception:
                    comp = []


        # 闭环幅相特性（Nichols + 四大闭环指标）
        nich = None
        try:
            nd = A.nichols(np.asarray(d["num"], float), np.asarray(d["den"], float))
            f2 = Figure(figsize=(9.6, 3.9), dpi=130)
            A.draw_nichols(f2, nd)
            f2.tight_layout(rect=(0, 0, 1, 0.93))
            _b = io.BytesIO()
            FigureCanvasAgg(f2)
            f2.savefig(_b, format="png", facecolor="#ffffff", dpi=130)
            uri_n = _store_img(_b.getvalue(), "webp")
            nich = {"img": "data:image/png;base64," + base64.b64encode(_b.getvalue()).decode(),
                    "img_url": uri_n,
                    "text": "M(0)=%.4f   Mr=%.4f (Wr=%.3f rad/s)   Wb=%.3f rad/s"
                            % (nd["M0"], nd["Mr"], nd["Wr"], nd["Wb"])}
        except Exception:
            traceback.print_exc()

        # 稳定性判据可视化（Routh / Nyquist / Bode / 单位圆 / Jury）
        stab = None
        try:
            if discrete:
                # 用文本重建 L(z)=D(z)G(z)，避免依赖 compute_z 的系数顺序
                if czl.has_var(g0, "z") and not czl.has_var(g0, "s"):
                    e0 = czl._parse(g0, czl.z, "G")
                    gn, gd = czl._coeffs(e0, czl.z)
                    gn = np.asarray(czl._trim(gn), float)
                    gd = np.asarray(czl._trim(gd), float)
                else:
                    ex = czl._parse(g0, czl.s, "G")
                    n0, d0 = czl._coeffs(ex, czl.s)
                    gn, gd = czl.zoh_tf(n0, d0, Tv)
                if has_cmp:
                    if czl.has_var(gc, "z"):
                        e2 = czl._parse(gc, czl.z, "Gc")
                        cn2, cd2 = czl._coeffs(e2, czl.z)
                    else:
                        e3 = czl._parse(gc, czl.s, "Gc")
                        c3n, c3d = czl._coeffs(e3, czl.s)
                        cn2, cd2 = czl.tustin_tf(c3n, c3d, Tv)
                else:
                    cn2, cd2 = np.array([1.0]), np.array([1.0])
                ln = np.polymul(np.asarray(cn2, float), np.asarray(gn, float))
                ld = np.polymul(np.asarray(cd2, float), np.asarray(gd, float))
                st = cst.analyse(ln, ld, discrete=True, T=Tv,
                                 kind=(nl if nl != "none" else "sat"),
                                 M=nlM, a=nla)
            else:
                st = cst.analyse(np.asarray(d["num"], float), np.asarray(d["den"], float),
                                 discrete=False, kind=(nl if nl != "none" else "sat"),
                                 M=nlM, a=nla)
            if nl == "none":
                st["df"] = None
            fig2 = Figure(figsize=(9.6, 6.5), dpi=118)
            cst.draw(fig2, st, zoom=nz)
            _suri, _sraw = _fig_to_data_uri(fig2, with_bytes=True)
            _surl = _store_img(_sraw, "png")
            _simgs = _split_panels(fig2, _sraw) if narrow else []
            if narrow and _simgs:
                _suri = ""
            stab = {"img": _suri,
                    "img_url": _surl,
                    "imgs": _simgs,
                    "stable": st["stable"],
                    "marginal": bool(st.get("marginal")),
                    "df": _df_payload(st.get("df")) if nl != "none" else None,
                    "text": _stab_text(st, discrete, nl)}
        except Exception:
            traceback.print_exc()
            stab = None

        tiles = _tiles_z(d, has_cmp) if discrete else _tiles(d, has_cmp, discrete)
        if not d["stable"]:
            for t in tiles:
                if t["label"] in ("超调量 σ", "调节时间 t<sub>s</sub>(2%)", "主导阻尼比 ζ"):
                    t["after"] = None
        elif d.get("marginal"):
            # 临界稳定：σ / t_s 不定义，指标卡直接不显示数值
            for t in tiles:
                if t["label"] in ("超调量 σ", "调节时间 t<sub>s</sub>(2%)"):
                    t["after"] = None

        # 公式回显：零极点形式 + 展开多项式形式（前端一键切换）
        formula = None
        try:
            fsrc = "G₀ = " + g0 + ((" ｜ Gc = " + gc) if has_cmp else "")
            if discrete:
                gcn = d.get("gc_num") if has_cmp else None
                gcd = d.get("gc_den") if has_cmp else None
                formula = cfx.build(d["g_num"], d["g_den"], d["num"], d["den"],
                                    gcn, gcd, discrete=True, T=Tv, src=fsrc,
                                    note=(d.get("note") or ""))
            else:
                gcn = gcd = None
                if has_cmp:
                    try:
                        gcn, gcd = cc.to_numden(gc)
                    except Exception:
                        gcn = gcd = None
                r0 = d["res"]["raw"]
                formula = cfx.build(r0["num"], r0["den"], d["num"], d["den"],
                                    gcn, gcd, discrete=False, src=fsrc)
        except Exception:
            traceback.print_exc()
            formula = None

        # 浏览器端实时联动用：连续、线性、阶跃时给出系数与特征量。
        # 前端只做快速预览；最终数值仍以 Python 内核为准。
        model = None
        nyq_model = None
        if not discrete:
            try:
                def _coef(v):
                    return [float(x) for x in np.asarray(v, float).ravel()]

                def _roots(v):
                    a = np.asarray(v, float)
                    if a.size <= 1:
                        return []
                    return [[float(z.real), float(z.imag)] for z in np.roots(a)]

                def _first(v):
                    try:
                        for x in np.asarray(v, float).ravel():
                            if np.isfinite(x):
                                return float(x)
                    except Exception:
                        pass
                    return None

                rr = d["res"]["cmp"] if has_cmp else d["res"]["raw"]
                cl_den = cc._polyadd_same(np.asarray(d["den"], float),
                                          np.asarray(d["num"], float))
                base = {
                    "ol_num": _coef(d["num"]),
                    "ol_den": _coef(d["den"]),
                    "cl_num": _coef(d["num"]),
                    "cl_den": _coef(cl_den),
                    "poles_ol": _roots(d["den"]),
                    "zeros_ol": _roots(d["num"]),
                    "poles_cl": _roots(cl_den),
                    "wc": _first(rr.get("wc")),
                    "pm": _first(rr.get("gm")),
                    "wg": _first(rr.get("wg")),
                    "stable": bool(d["stable"]),
                    "marginal": bool(d.get("marginal", False)),
                    "has_cmp": bool(has_cmp),
                    "e_ss": _num(d.get("e_ss", 0.0)),
                    "nl": nl,
                    "M": float(nlM),
                    "a": float(nla),
                }
                nyq_model = base
                if nl == "none" and kind == "step":
                    model = dict(base)
            except Exception:
                traceback.print_exc()
                model = None
                nyq_model = None

    return {"ok": True, "nich": nich, "img": uri, "img_url": _img_url, "imgs": _imgs, "text": text, "mode": mode,
            "tiles": tiles, "comp": comp, "domainNote": domainNote,
            "stab": stab, "panel": panel, "nl": nl, "kind": kind, "nlM": nlM, "nla": nla,
            "formula": formula,
            "model": model,
            "nyq_model": nyq_model,
            "nz": nz,
            "stable": bool(d["stable"]),
            "marginal": bool(d.get("marginal", False))}


class Handler(BaseHTTPRequestHandler):
    server_version = "CtrlCheckWeb/2.0"

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # no-store：改完 html/css/js 刷新即可见，不用清缓存
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            body = _read(os.path.join(TPL_DIR, "index.html"))
            if body is None:
                self._send(500, "缺少 templates/index.html".encode("utf-8"),
                           "text/plain; charset=utf-8")
            else:
                self._send(200, body, "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            name = os.path.basename(path[len("/static/"):])
            body = _read(os.path.join(STATIC_DIR, name))
            if body is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
            else:
                ext = os.path.splitext(name)[1].lower()
                self._send(200, body, _MIME.get(ext, "application/octet-stream"))
        elif path.startswith("/img/"):
            key = os.path.basename(path)
            raw = _IMG_CACHE.get(key)
            if raw is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
            else:
                ct = "image/webp" if key.endswith(".webp") else "image/png"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(raw)
        elif path == "/favicon.ico":
            self._send(200, ICON_SVG.encode("utf-8"), "image/svg+xml")
        elif path == "/icon.svg":
            self._send(200, ICON_SVG.encode("utf-8"), "image/svg+xml")
        elif path == "/manifest.webmanifest":
            self._send(200, json.dumps(MANIFEST, ensure_ascii=False).encode("utf-8"),
                       "application/manifest+json; charset=utf-8")
        else:
            self._send(404, b'{"ok":false,"err":"not found"}')

    def do_POST(self):
        if urlsplit(self.path).path != "/api":
            self._send(404, b'{"ok":false,"err":"not found"}')
            return
        key = None
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) or b"{}"
            req = json.loads(raw)
            key = json.dumps(req, sort_keys=True, ensure_ascii=False)
            with _CACHE_LOCK:
                hit = _CACHE.get(key)
                if hit is not None:
                    _CACHE.move_to_end(key)
            if hit is not None:
                self._send(200, hit)
                return
            res = analyse(req)
            body = json.dumps(_json_safe(res), ensure_ascii=False,
                              allow_nan=False).encode("utf-8")
            if res.get("ok"):
                with _CACHE_LOCK:
                    _CACHE[key] = body
                    while len(_CACHE) > _CACHE_MAX:
                        _CACHE.popitem(last=False)
            self._send(200, body)
            return
        except Exception as exc:
            traceback.print_exc()
            msg = str(exc) or exc.__class__.__name__
            res = {"ok": False, "err": msg}
        self._send(200, json.dumps(_json_safe(res), ensure_ascii=False,
                                   allow_nan=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] %s\n" % (fmt % args))


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser(description="控制校正验算器 网页版")
    ap.add_argument("-p", "--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    a = ap.parse_args()

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    ip = local_ip()
    print("=" * 56)
    print("  控制校正验算器 · 网页版已启动")
    print("  本机访问 : http://127.0.0.1:%d" % a.port)
    print("  手机访问 : http://%s:%d   （需同一个 Wi-Fi）" % (ip, a.port))
    print("  停止服务 : Ctrl+C")
    print("=" * 56)
    if not a.no_open:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:%d" % a.port)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.server_close()


if __name__ == "__main__":
    main()
