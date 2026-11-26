"""非线性环节的闭环时域仿真（连续 / 离散）。

非线性元件放在误差通道（单位负反馈）：
    e = r - y,  u = N(e),  y = G u

支持：
  relay     理想继电器      u = M·sign(e)
  relay_dz  带死区继电器    |e|>a 时 ±M，否则 0
  sat       饱和             u = clip(e, -a, a)

连续系统用可控/可观标准型 + 定步长 RK4（非线性输出在每步内保持，
并对直接通道 D≠0 做少量不动点迭代）；离散系统用差分方程逐拍递推。
"""
from __future__ import annotations

import numpy as np

NL_NAMES = {
    "relay": "理想继电器",
    "relay_dz": "带死区继电器",
    "sat": "饱和",
    "relay_hyst": "滞环继电器",
}


def _nl(kind, e, M=1.0, a=1.0, u_prev=0.0):
    e = np.asarray(e, float)
    if kind == "relay":
        return M * np.sign(e)
    if kind == "relay_dz":
        return np.where(e > a, M, np.where(e < -a, -M, 0.0))
    if kind == "relay_hyst":
        if e >= a: return M
        if e <= -a: return -M
        return u_prev
    # sat：线性区 ±a，斜率 1
    return np.clip(e, -a, a)


def _desc(kind, M, a):
    if kind == "relay":
        return f"理想继电器，M={M:g}"
    if kind == "relay_dz":
        return f"带死区继电器，M={M:g}，a={a:g}"
    if kind == "relay_hyst":
        return f"滞环继电器，M={M:g}，阈值 a={a:g}"
    return f"饱和，线性区 ±{a:g}（M 不参与）"


def _input_signal(t, kind):
    t = np.asarray(t, float)
    if kind == "ramp":
        return t.copy()
    if kind == "accel":
        return 0.5 * t * t
    return np.ones_like(t)


def _horizon(den, num, T=None):
    """按闭环极点估一个能看完响应的仿真时长。"""
    if T is not None:
        return float(T), None
    ch = np.asarray(den, float).copy()
    ch[-len(num):] += np.asarray(num, float)
    poles = np.roots(ch) if len(ch) > 1 else np.array([])
    if poles.size == 0:
        return 5.0, poles
    re = poles.real
    pos = re[re > 1e-9]
    if pos.size:
        return float(np.clip(3.0 / pos.max(), 1e-4, 5000.0)), poles
    slow = np.min(np.abs(re)) if np.any(re) else 1.0
    fast = np.max(np.abs(poles))
    return float(np.clip(min(12.0 / max(slow, 1e-9),
                             400.0 / max(fast, 1e-9)), 1e-4, 5000.0)), poles


def _ss(num, den):
    """连续传函 -> 可观标准型 (A,B,C,D)，降幂系数。"""
    den = np.asarray(den, float)
    num = np.asarray(num, float)
    n = len(den) - 1
    a = den / den[0]
    b = np.zeros(n + 1)
    b[-len(num):] = num / den[0]
    if n == 0:
        return None, None, None, float(b[0])
    A = np.zeros((n, n))
    for i in range(n):
        A[i, 0] = -a[i + 1]
        if i + 1 < n:
            A[i, i + 1] = 1.0
    B = np.array([b[i + 1] - b[0] * a[i + 1] for i in range(n)])
    C = np.zeros(n)
    C[0] = 1.0
    return A, B, C, float(b[0])


def simulate(num, den, kind="step", nl="relay", M=1.0, a=1.0, npts=4001):
    """连续闭环非线性仿真 -> (t, y, u, desc)。"""
    num = np.asarray(num, float)
    den = np.asarray(den, float)
    if nl not in NL_NAMES:
        raise ValueError("未知非线性环节：%s" % nl)
    T, _poles = _horizon(den, num)
    t = np.linspace(0.0, T, int(npts))
    r = _input_signal(t, kind)
    A, B, C, D = _ss(num, den)
    desc = _desc(nl, M, a)

    if A is None:                       # 纯增益：代数环
        x = None
        y = np.empty_like(t)
        u = np.empty_like(t)
        yk = 0.0
        up = 0.0
        for k, rk in enumerate(r):
            for _ in range(80):
                uk = _nl(nl, rk - yk, M, a, up)
                yk = D * uk
            y[k] = yk
            u[k] = uk
            up = uk
        return t, y, u, desc

    n = A.shape[0]
    dt = float(t[1] - t[0])
    x = np.zeros(n)
    y = np.empty_like(t)
    u = np.empty_like(t)
    y_prev = 0.0
    u_prev = 0.0
    # 理想继电器在零附近用极窄的数值滞环，抑制定步长仿真在切换点的高频抖动
    relay_eps = max(1e-6, 0.002 * max(1.0, abs(M)))
    for k, rk in enumerate(r):
        e = rk - y_prev
        if nl == "relay":
            if e > relay_eps:
                uk = M
            elif e < -relay_eps:
                uk = -M
            else:
                uk = u_prev
        else:
            uk = float(_nl(nl, e, M, a, u_prev))
        if abs(D) > 1e-12:
            for _ in range(6):
                yk = float(C @ x + D * uk)
                uk = float(_nl(nl, rk - yk, M, a, u_prev))
        k1 = A @ x + B * uk
        k2 = A @ (x + 0.5 * dt * k1) + B * uk
        k3 = A @ (x + 0.5 * dt * k2) + B * uk
        k4 = A @ (x + dt * k3) + B * uk
        x = x + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        yk = float(C @ x + D * uk)
        y[k], u[k] = yk, uk
        y_prev = yk
        u_prev = uk
    return t, y, u, desc


def free_response(num, den, T_end, npts=6001, nl="relay_hyst", M=1.0, a=1.0, y0=1.0):
    """零输入自由响应（e = −y），用来判断描述函数算出的自振点是否稳定。

    与 simulate 同样的定步长 RK4 与开关逻辑，只是输入恒为 0、初值 y(0)=y0。
    """
    num = np.asarray(num, float)
    den = np.asarray(den, float)
    if nl not in NL_NAMES:
        raise ValueError("未知非线性环节：%s" % nl)
    npts = max(201, int(npts))
    t = np.linspace(0.0, float(T_end), npts)
    A, B, C, D = _ss(num, den)
    if A is None:
        return None
    n = A.shape[0]
    dt = float(t[1] - t[0])
    x = np.zeros(n)
    if n:
        x[0] = float(y0)
    y = np.empty_like(t)
    u_prev = 0.0
    y_prev = float(C @ x)
    for k in range(npts):
        e = -y_prev
        uk = float(_nl(nl, e, M, a, u_prev))
        k1 = A @ x + B * uk
        k2 = A @ (x + 0.5 * dt * k1) + B * uk
        k3 = A @ (x + 0.5 * dt * k2) + B * uk
        k4 = A @ (x + dt * k3) + B * uk
        x = x + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        y[k] = float(C @ x)
        y_prev = y[k]
        u_prev = uk
    return t, y


def simulate_z(num, den, T, kind="step", nl="relay", M=1.0, a=1.0, npts=2001):
    """离散闭环非线性仿真 -> (t, y, u, desc)。"""
    num = np.asarray(num, float)
    den = np.asarray(den, float)
    if nl not in NL_NAMES:
        raise ValueError("未知非线性环节：%s" % nl)
    n = len(den) - 1
    if n <= 0:
        raise ValueError("离散非线性仿真需要至少一阶系统")
    ad = den / den[0]
    b = np.zeros(n + 1)
    b[-len(num):] = num / den[0]
    ch = den.copy()
    ch[-len(num):] += num
    poles = np.roots(ch) if len(ch) > 1 else np.array([])
    rmax = float(np.max(np.abs(poles))) if poles.size else 0.0
    if rmax < 1.0:
        # 最慢模态 e^{-sT} ≈ pole^N，取 0.8% 残差
        need = int(np.ceil(np.log(0.008) / np.log(max(rmax, 1e-6))))
    else:
        need = 300
    N = int(np.clip(max(npts, need + 1), 200, 6000))
    t = np.arange(N) * float(T)
    r = _input_signal(t, kind)
    y = np.zeros(N)
    u = np.zeros(N)
    up = 0.0
    desc = _desc(nl, M, a) + f"，T={T:g}s"

    for k in range(N):
        # 右端只依赖过去时刻
        rest = 0.0
        for i in range(1, n + 1):
            if k - i >= 0:
                rest += b[i] * u[k - i] - ad[i] * y[k - i]
        if abs(b[0]) < 1e-12:
            yk = rest / ad[0]
            uk = float(_nl(nl, r[k] - yk, M, a, up))
            y[k], u[k] = yk, uk
            up = uk
        else:
            yk = y[k - 1] if k else 0.0
            uk = 0.0
            for _ in range(40):
                uk = float(_nl(nl, r[k] - yk, M, a, up))
                yk = (b[0] * uk + rest) / ad[0]
            y[k], u[k] = yk, uk
            up = uk
    return t, y, u, desc
