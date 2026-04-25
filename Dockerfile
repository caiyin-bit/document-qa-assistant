FROM python:3.12-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# `src/` is imported as a top-level package (e.g. `from src.main import …`),
# but uv sync uses --no-install-project so the venv doesn't contain it.
# Make /app discoverable on sys.path explicitly — both for `uv run uvicorn`
# (which doesn't add cwd to sys.path) and for `python scripts/seed_…`.
ENV PYTHONPATH=/app

# Dependency layer (cached): install third-party deps WITHOUT trying to
# install our own project (src/ isn't copied yet). --no-install-project
# is essential — without it, uv sync would fail because pyproject.toml
# declares the local project but its source dir is missing.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Now copy source (will be overridden by bind mount in dev).
COPY src ./src
COPY persona ./persona
COPY scripts ./scripts
COPY config.yaml alembic.ini ./

EXPOSE 8000
