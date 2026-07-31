FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MCP_HOSTED=1
ENV PORT=8000
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
COPY cartesia_mcp ./cartesia_mcp

RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000

CMD ["cartesia-mcp", "--transport", "streamable-http"]
