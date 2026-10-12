# Career Coach: the backend and the built website in one image.
# Built for linux/arm64 (the Graviton server in infra/career-coach.yaml) by
# .github/workflows/publish-image.yml and published to Amazon ECR Public.
# Base images are pinned by digest; the tags are there for people reading this.

# ---------- 1. Build the website ----------
FROM public.ecr.aws/docker/library/node:22.23.3-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# same-origin: the backend serves the site, so the API lives at the same address.
RUN VITE_API_BASE_URL=same-origin npm run build

# ---------- 2. Install the backend's Python packages ----------
FROM public.ecr.aws/docker/library/python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS deps
COPY --from=ghcr.io/astral-sh/uv:0.10.4@sha256:4cac394b6b72846f8a85a7a0e577c6d61d4e17fe2ccee65d9451a8b3c9efb4ac /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---------- 3. The image that runs ----------
FROM public.ecr.aws/docker/library/python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin coach
WORKDIR /app/backend
COPY --from=deps /app/backend/.venv ./.venv
COPY backend/pyproject.toml ./
COPY backend/coach ./coach
COPY --from=web /src/frontend/dist /app/frontend/dist
RUN mkdir -p /app/data && chown coach /app/data

ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    COACH_HOST=0.0.0.0 \
    COACH_PORT=8000 \
    COACH_STATIC_DIR=/app/frontend/dist \
    COACH_DATA_DIR=/app/data

USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["python", "-m", "coach"]
