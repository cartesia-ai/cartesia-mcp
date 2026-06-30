FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MCP_HOSTED=1
ENV PORT=8000

COPY pyproject.toml README.md ./
COPY cartesia_mcp ./cartesia_mcp

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["cartesia-mcp", "--transport", "streamable-http"]
