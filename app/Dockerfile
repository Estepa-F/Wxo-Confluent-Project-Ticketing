FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Separate layer from the app code below so dependency installs are
# cached across builds that only change support_portal/.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY support_portal/ ./support_portal/
RUN uv sync --frozen

RUN useradd --create-home --uid 1000 portal && chown -R portal:portal /app
USER portal

# Config is entirely env-var driven (see .env.example) -- pass real
# values with `docker run --env-file` or your host's secret mechanism,
# never bake a real .env into the image.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", 8000)}/status', timeout=3)" || exit 1

CMD ["uv", "run", "python", "-m", "support_portal"]
