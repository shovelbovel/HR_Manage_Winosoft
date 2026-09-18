# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# WeasyPrint (Module 7) links against these at runtime, not just build
# time — needed in every stage that imports weasyprint, dev and prod alike.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    fonts-dejavu-core \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer first so it's cached independently of app code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app
RUN uv sync --frozen --no-dev


FROM builder AS dev
# Dev image keeps uv + dev-dependencies (pytest, ruff) and expects app/,
# scripts/, tests/ to be bind-mounted by docker-compose for hot reload.
RUN uv sync --frozen
COPY scripts ./scripts
COPY tests ./tests
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM python:3.12-slim AS prod
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    fonts-dejavu-core \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
COPY scripts ./scripts
# Only the trained artifact ships to prod — the raw dataset, training
# script and evaluation plots are dev-only (see ml/train_attrition_model.py).
# Requires the model to already be trained on the host before building this
# image: docker compose exec app uv run python ml/train_attrition_model.py
COPY ml/artifacts ./ml/artifacts
ENV PATH="/app/.venv/bin:$PATH"
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
