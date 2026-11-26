# 控制校正验算器 · 网页版镜像
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    DEBIAN_FRONTEND=noninteractive

# 中文字体（不装图上全是方块）
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-cjk fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ctrl_*.py ./
COPY templates ./templates
COPY static ./static
RUN pip install --no-cache-dir numpy matplotlib sympy

EXPOSE 8000
CMD ["python", "ctrl_web.py", "--host", "0.0.0.0", "--port", "8000", "--no-open"]
