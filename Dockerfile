FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# eMudhra/emSign CA key compromise (2026-10, DSA-6572-1): refuse to build on a
# Debian trust store that still contains "emSign ECC Root CA - G3".
RUN . /etc/os-release && case "$VERSION_CODENAME" in \
      bookworm) min=20250419~deb12u2 ;; \
      trixie)   min=20250419+deb13u1 ;; \
      *) echo "unhandled Debian codename: $VERSION_CODENAME" >&2; exit 1 ;; \
    esac \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge "$min"

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

RUN uv sync --frozen --no-dev --no-editable --extra hosted

EXPOSE 8000

CMD ["ddtrace-run", "cartesia-mcp", "--transport", "streamable-http"]
