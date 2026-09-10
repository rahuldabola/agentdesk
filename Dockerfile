FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY data ./data
COPY scripts ./scripts

# The MCP tool server is launched as a subprocess by the API, so both live in
# this image; only the HTTP port is exposed.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Ingesting is idempotent (each file's old chunks are deleted before its new
# ones are added) and cheap for this corpus, so it's simplest to run it fresh
# on every boot rather than bake an embedded chroma_db into the image.
CMD python -m scripts.ingest_docs && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
