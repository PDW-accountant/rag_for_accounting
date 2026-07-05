FROM node:22-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    FRONTEND_DIST_DIR="/app/frontend/dist"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
# --extra reranker: USE_RERANKER 기본값이 켜져 있어 리랭커(bge-reranker-v2-m3)를 이 컨테이너 안에서 직접 로드한다.
# sentence-transformers+torch가 없으면 리랭커 import가 실패해 조용히 폴백하므로, 여기서 함께 설치한다.
RUN uv sync --frozen --no-dev --extra reranker

COPY src/ ./src/
RUN mkdir -p ./data/raw
COPY --from=frontend-builder /frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
