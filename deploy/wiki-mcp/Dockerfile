FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "mcp>=1.12,<2" pyyaml uvicorn starlette

WORKDIR /app
COPY deploy/wiki-mcp/entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENV WIKI_ROOT=/wiki WIKI_MCP_HOST=0.0.0.0 WIKI_MCP_PORT=8765 WIKI_MCP_PUSH=1
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/health')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
