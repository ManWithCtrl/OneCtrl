# -*- coding: utf-8 -*-
"""
ctrl_formula.py —— 公式回显

把数值内核算出的传递函数（分子/分母系数）排成浏览器可直接渲染的
Presentation MathML，不依赖 MathJax/KaTeX，离线也能用。

对外只有 build()：
    build(num0, den0, numL, denL, gc_num=None, gc_den=None,
          discrete=False, T=None, src="", note="")

返回 {"var", "note", "src", "rows":[{"label","math","poly","note"}]}
其中 math 是零极点形式，poly 是展开多项式形式，前端一键切换。
"""
from __future__ import annotations

import numpy as np

EPS = 1e-9


# ------------------------------------------------------------------ 小工具
def _trim(c):
    c = np.asarray(c, dtype=float).ravel()
    nz = np.nonzero(np.abs(c) > 1e-14)[0]
    if not nz.size:
        return np.array([0.0])
    return c[nz[0]:]


def _polyadd(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = max(len(a), len(b))
    return (np.concatenate([np.zeros(n - len(a)), a])
            + np.concatenate([np.zeros(n - len(b)), b]))


def _round(x, nd=6):
    x = float(x)
    if not np.isfinite(x):
        return 0.0
    if abs(x) < 1e-10:
        return 0.0
    v = round(x, nd)
    if abs(v - round(v)) < 1e-9:
        v = float(round(v))
    return v


def _plain(x, nd=4):
    x = float(x)
    if not np.isfinite(x):
        return "∞"
    ax = abs(x)
    if ax >= 1e6 or (ax and ax < 1e-4):
        return "%.3e" % x
    return "%.*g" % (nd, x)


def _num_ml(x):
    """数字 → MathML（大数/小数用科学计数法，避免一行放不下）"""
    x = _round(x)
    if abs(x) < EPS:
        return "<mn>0</mn>"
    ax = abs(x)
    if 1e-4 <= ax < 1e6:
        s = ("%.6g" % ax)
        return "<mn>%s</mn>" % s
    exp = int(np.floor(np.log10(ax)))
    mant = ax / (10.0 ** exp)
    ms = ("%.3g" % mant)
    return ("<mrow><mn>%s</mn><mo>&#xd7;</mo>"
            "<msup><mn>10</mn><mn>%d</mn></msup></mrow>" % (ms, exp))


def _pow(base_ml, n):
    if n <= 1:
        return base_ml
    return "<msup><mrow>%s</mrow><mn>%d</mn></msup>" % (base_ml, n)


def _math(inner):
    return ('<math xmlns="http://www.w3.org/1998/Math/MathML" '
            'display="block"><mrow>%s</mrow></math>' % inner)


# ------------------------------------------------------------ 多项式 → MathML
def _poly_ml(coeffs, var="s"):
    c = _trim(coeffs)
    deg = len(c) - 1
    parts = []
    for i, v in enumerate(c):
        p = deg - i
        v = _round(v)
        if abs(v) < 1e-12:
            continue
        neg = v < 0
        a = abs(v)
        if parts:
            parts.append("<mo>−</mo>" if neg else "<mo>+</mo>")
        elif neg:
            parts.append("<mo>−</mo>")

        coef = None
        if p == 0 or abs(a - 1.0) > 1e-12:
            coef = _num_ml(a)
        if p == 0:
            parts.append(coef)
        elif p == 1:
            if coef:
                parts.append(coef + "<mo>&#x2062;</mo>")
            parts.append("<mi>%s</mi>" % var)
        else:
            if coef:
                parts.append(coef + "<mo>&#x2062;</mo>")
            parts.append("<msup><mi>%s</mi><mn>%d</mn></msup>" % (var, p))
    if not parts:
        return "<mn>0</mn>"
    return "<mrow>%s</mrow>" % "".join(parts)


# ------------------------------------------------------------ 根 → 零极点因子
def _clusters(roots):
    """把数值上重合的根并成一簇（重根/重极点）。"""
    cl = []
    for x in roots:
        x = complex(x)
        for c in cl:
            if abs(x - c[0]) <= 1e-6 * max(1.0, abs(x)):
                c[0] = (c[0] * c[1] + x) / (c[1] + 1)
                c[1] += 1
                break
        else:
            cl.append([x, 1])
    cl.sort(key=lambda c: (round(c[0].real, 6), round(c[0].imag, 6)))
    return cl


def _real_factor(r, var):
    r = _round(r.real)
    if abs(r) < EPS:
        return "<mi>%s</mi>" % var
    if r < 0:
        return ("<mrow><mo>(</mo><mi>%s</mi><mo>+</mo>%s<mo>)</mo></mrow>"
                % (var, _num_ml(-r)))
    return ("<mrow><mo>(</mo><mi>%s</mi><mo>−</mo>%s<mo>)</mo></mrow>"
            % (var, _num_ml(r)))


def _quad_factor(a, b, var):
    """(s^2 - 2a s + a^2+b^2)，a、b 为实数部分与虚部。"""
    a, b = _round(a, 5), _round(abs(b), 5)
    c = _round(a * a + b * b, 5)
    inner = "<msup><mi>%s</mi><mn>2</mn></msup>" % var
    coef = _round(-2.0 * a, 5)
    if abs(coef) > 1e-9:
        inner += "<mo>−</mo>" if coef < 0 else "<mo>+</mo>"
        av = abs(coef)
        if abs(av - 1.0) > 1e-9:
            inner += _num_ml(av) + "<mo>&#x2062;</mo>"
        inner += "<mi>%s</mi>" % var
    if abs(c) > 1e-9:
        inner += ("<mo>+</mo>" if c > 0 else "<mo>−</mo>") + _num_ml(abs(c))
    return "<mrow><mo>(</mo>%s<mo>)</mo></mrow>" % inner


def _factor_parts(roots, var):
    cl = _clusters(roots)
    done = set()
    out = []
    for i, (r, n) in enumerate(cl):
        if i in done:
            continue
        if abs(r.imag) <= 1e-6 * max(1.0, abs(r)):
            out.append(_pow(_real_factor(r, var), n))
            done.add(i)
            continue
        partner = r.conjugate()
        show = r if r.imag > 0 else partner
        m = n
        for j, (q, k) in enumerate(cl):
            if j == i or j in done:
                continue
            if abs(q - partner) <= 1e-5 * max(1.0, abs(q)):
                m = max(m, k)
                done.add(j)
        done.add(i)
        out.append(_pow(_quad_factor(show.real, show.imag, var), m))
    return out


def _product(parts):
    if not parts:
        return "<mn>1</mn>"
    if len(parts) == 1:
        return parts[0]
    return "<mrow>%s</mrow>" % "<mo>&#x2062;</mo>".join(parts)


def _zp_inner(num, den, var):
    """零极点形式的 MathML（内部，不含 <math> 包装）。"""
    num, den = _trim(num), _trim(den)
    if not np.any(np.abs(num) > 0):
        return "<mn>0</mn>"
    k = float(num[0]) / float(den[0])
    zp = _factor_parts(np.roots(num) if len(num) > 1 else [], var)
    pp = _factor_parts(np.roots(den) if len(den) > 1 else [], var)

    kk = _round(k, 8)
    neg = kk < 0
    coeff = None
    if abs(abs(kk) - 1.0) > 1e-9:
        coeff = _num_ml(abs(kk))
    head = ([coeff] if coeff else []) + zp
    num_ml = _product(head)
    if neg:
        num_ml = "<mo>−</mo>" + num_ml
    if not pp:
        return num_ml
    return "<mfrac>%s%s</mfrac>" % (num_ml, _product(pp))


# ------------------------------------------------------------ 说明文字
def _note_tf(num, den, var, discrete=False, with_type=False):
    num, den = _trim(num), _trim(den)
    p = np.roots(den) if len(den) > 1 else np.array([])
    z = np.roots(num) if len(num) > 1 else np.array([])
    bits = ["%d 个极点" % p.size]
    if z.size:
        bits.append("%d 个零点" % z.size)
    if abs(den[0]) > 0:
        bits.append("增益 K = " + _plain(num[0] / den[0]))

    xv = 1.0 if discrete else 0.0
    dv = float(np.polyval(den, xv))
    if abs(dv) > 1e-12:
        dc = float(np.polyval(num, xv)) / dv
        bits.append(("L(1)" if discrete else "L(0)") + " = " + _plain(dc))

    if with_type:
        if discrete:
            n1 = int(np.sum(np.abs(p - 1.0) < 1e-7))
            if n1:
                bits.append("z=1 处 %d 重积分" % n1)
        else:
            n0 = int(np.sum(np.abs(p) < 1e-7))
            if n0:
                bits.append("%s型（%d 重积分）" % ("I" if n0 == 1 else "II", n0))
            else:
                bits.append("0 型")
    return " · ".join(bits)


def _stability(den_cl, discrete=False):
    d = _trim(den_cl)
    if len(d) <= 1:
        return True
    r = np.roots(d)
    if discrete:
        return bool(np.all(np.abs(r) < 1.0 + 1e-9))
    return bool(np.all(r.real < 1e-9))


# ------------------------------------------------------------------ 对外
def build(num0, den0, numL, denL, gc_num=None, gc_den=None,
          discrete=False, T=None, src="", note=""):
    var = "z" if discrete else "s"
    num0, den0 = _trim(num0), _trim(den0)
    numL, denL = _trim(numL), _trim(denL)
    rows = []
    has_gc = (gc_num is not None and gc_den is not None
              and np.any(np.abs(gc_num) > 0))

    g0_label = "G₀(%s) =" % var
    rows.append(dict(
        label=g0_label,
        math=_math(_zp_inner(num0, den0, var)),
        poly=_math(_fraction_poly(num0, den0, var)),
        note=_note_tf(num0, den0, var, discrete) + (" · " + note if note else ""),
    ))

    if has_gc:
        gc_num, gc_den = _trim(gc_num), _trim(gc_den)
        rows.append(dict(
            label="Gc(%s) =" % var,
            math=_math(_zp_inner(gc_num, gc_den, var)),
            poly=_math(_fraction_poly(gc_num, gc_den, var)),
            note=_note_tf(gc_num, gc_den, var, discrete),
        ))

    l_label = "L(%s) = Gc(%s)G₀(%s) =" % (var, var, var) if has_gc \
        else "L(%s) = G₀(%s) =" % (var, var)
    rows.append(dict(
        label=l_label,
        math=_math(_zp_inner(numL, denL, var)),
        poly=_math(_fraction_poly(numL, denL, var)),
        note=_note_tf(numL, denL, var, discrete, with_type=True),
    ))

    den_cl = _polyadd(denL, numL)
    stable = _stability(den_cl, discrete)
    _marginal = False
    try:
        if stable and len(den_cl) > 1:
            _r = np.roots(den_cl)
            _marginal = bool(np.any(np.abs(np.real(_r)) < 1e-9))
    except Exception:
        _marginal = False
    _stab_txt = "临界稳定" if _marginal else ("稳定" if stable else "不稳定")
    rows.append(dict(
        label="Φ(%s) = L / (1 + L) =" % var,
        math=_math(_zp_inner(numL, den_cl, var)),
        poly=_math(_fraction_poly(numL, den_cl, var)),
        note="闭环 %d 个极点 · %s" % (len(_trim(den_cl)) - 1, _stab_txt),
    ))

    lead = float(den_cl[0]) if abs(den_cl[0]) > 0 else 1.0
    monic = den_cl / lead
    if len(monic) > 1:
        eq = _poly_ml(monic, var) + "<mo>=</mo><mn>0</mn>"
        rows.append(dict(
            label="特征方程（1 + L = 0）",
            math=_math(eq),
            poly=_math(eq),
            note="首项归一 · 共 %d 阶" % (len(monic) - 1),
        ))

    top = "%s系统 · 单位负反馈" % ("离散" if discrete else "连续")
    if discrete and T:
        top = "离散系统 · T = %g s · 单位负反馈" % float(T)

    def _c(a):
        return [float(x) for x in np.asarray(a, dtype=float).ravel()]

    data = {
        "var": var,
        "discrete": bool(discrete),
        "T": float(T) if T else None,
        "g0": {"num": _c(num0), "den": _c(den0)},
        "gc": ({"num": _c(gc_num), "den": _c(gc_den)} if has_gc else None),
        "L": {"num": _c(numL), "den": _c(denL)},
        "cl": {"num": _c(numL), "den": _c(den_cl)},
    }
    return {"var": var, "note": top, "src": src, "rows": rows,
            "stable": stable, "data": data}


def _fraction_poly(num, den, var):
    n = _poly_ml(num, var)
    d = _poly_ml(den, var)
    if _trim(den).size == 1 and abs(float(_trim(den)[0]) - 1.0) < 1e-12:
        return n
    return "<mfrac>%s%s</mfrac>" % (n, d)
