# syntax=docker/dockerfile:1

# The converter: Node 24 with the pinned fragments, web-ifc and three packages.
FROM node:24-bookworm-slim AS converter
WORKDIR /app/converter
COPY converter/package.json converter/package-lock.json ./
RUN npm ci --omit=dev
COPY converter/convert.mjs converter/lines.mjs ./

# The kern: Python 3.12 with openbim_kern, plus the node binary and the converter.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENBIM_KERN_DATA=/data \
    OPENBIM_OMZETTER_CMD="node /app/converter/convert.mjs"
COPY --from=converter /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf src
COPY --from=converter /app/converter ./converter
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin openbim \
    && mkdir -p /data && chown openbim /data
USER openbim
VOLUME ["/data"]
EXPOSE 8730
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8730/v1/health', timeout=3)"]
CMD ["openbim-kern", "serve", "--host", "0.0.0.0", "--poort", "8730"]
