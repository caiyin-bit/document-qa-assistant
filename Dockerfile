FROM python:3.12-slim

# Use Chinese PyPI mirror to avoid timeouts on cn networks.
# UV_DEFAULT_INDEX overrides the default PyPI index for uv;
# pyproject.toml's [tool.uv.sources] torch=pytorch-cpu still wins
# for torch (explicit=true), so torch keeps using its own CPU wheel index.
ENV UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# Install uv (use Tsinghua pip mirror so uv itself installs fast)
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv

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
#
# NOTE: --frozen omitted on purpose. uv.lock pins exact wheel URLs at
# files.pythonhosted.org, which times out from cn networks. Without
# --frozen, uv re-resolves through UV_DEFAULT_INDEX (Tsinghua) above.
# Trade-off: reproducibility weakened, but acceptable for dev images.
COPY pyproject.toml uv.lock ./
# vendor/ holds wheels for deps Tsinghua's PyPI mirror serves intermittently
# (currently just zhconv). UV_FIND_LINKS makes uv prefer them over network
# fetches, which keeps `uv sync` deterministic on CN networks.
COPY vendor/ ./vendor/
ENV UV_FIND_LINKS=/app/vendor
RUN uv sync --no-dev --no-install-project

# Now copy source (will be overridden by bind mount in dev).
COPY src ./src
COPY persona ./persona
COPY scripts ./scripts
COPY config.yaml alembic.ini ./

RUN mkdir -p /app/data/uploads/.tmp

EXPOSE 8000
