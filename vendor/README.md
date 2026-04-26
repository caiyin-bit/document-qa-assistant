# vendored wheels

Pre-downloaded `.whl` files for deps that PyPI mirrors don't reliably
serve from inside the docker build network.

The `Dockerfile` installs everything here via `uv pip install --offline`
**after** the main `uv sync` step.

## current contents

| package | version | reason |
|---------|---------|--------|
| `zhconv` | 1.4.3 | 繁简归一化 — Tsinghua PyPI mirror times out from CN docker networks |

## adding a new vendored wheel

```bash
# 1. download the wheel on the host (where networking works)
uv pip download <pkg>==<ver> --dest ./vendor/ --no-deps

# 2. add it to the Dockerfile's `uv pip install --offline` step
# 3. commit both the wheel + Dockerfile change
```
