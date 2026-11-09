# syntax=docker/dockerfile:1

# Built from the root of the repository (the licence texts and the release scripts live there):
#   docker build -f kern/Dockerfile -t openbim-kern .
# A release build sets VERSIE, TAG and COMMIT (see .github/workflows/release.yml); they end up in /app/bron.json.

# The converter: Node 24 with the pinned fragments, web-ifc and three packages.
FROM node:24-bookworm-slim AS converter
WORKDIR /app/converter
COPY kern/converter/package.json kern/converter/package-lock.json ./
RUN npm ci --omit=dev
COPY kern/converter/convert.mjs kern/converter/lines.mjs ./

# The kern: Python 3.12 with openbim_kern, plus the node binary and the converter.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENBIM_KERN_DATA=/data \
    OPENBIM_OMZETTER_CMD="node /app/converter/convert.mjs"
COPY --from=converter /usr/local/bin/node /usr/local/bin/node
COPY --from=converter /usr/local/LICENSE /usr/local/share/doc/node/LICENSE
WORKDIR /app
COPY kern/pyproject.toml ./
COPY kern/src ./src
RUN pip install --no-cache-dir . && rm -rf src build
COPY --from=converter /app/converter ./converter

# Licence, notices and bron.json last, so a new release reuses every layer above.
COPY COPYING COPYING.LESSER ./
COPY scripts/release/notices.py scripts/release/bron.py /tmp/release/
ARG VERSIE=dev
ARG TAG=
ARG COMMIT=
RUN python /tmp/release/notices.py image THIRD-PARTY-NOTICES.txt --node-license /usr/local/share/doc/node/LICENSE \
    && python /tmp/release/bron.py bron.json --version "$VERSIE" --tag "$TAG" --commit "$COMMIT" \
    && rm -rf /tmp/release
ENV OPENBIM_KERN_RELEASE=${TAG}
LABEL org.opencontainers.image.title="Open BIM Platform: BIM-kern" \
      org.opencontainers.image.description="Rekenkern van het Open BIM Platform: omzetten, eigenschappen, koppelen en botsingen, over HTTP en MCP" \
      org.opencontainers.image.source="https://github.com/OpenAEC-Foundation/open-bim-platform" \
      org.opencontainers.image.licenses="LGPL-3.0-or-later" \
      org.opencontainers.image.vendor="OpenAEC Foundation" \
      org.opencontainers.image.version="${VERSIE}" \
      org.opencontainers.image.revision="${COMMIT}"

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin openbim \
    && mkdir -p /data && chown openbim /data
USER openbim
VOLUME ["/data"]
EXPOSE 8730
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8730/v1/health', timeout=3)"]
CMD ["openbim-kern", "serve", "--host", "0.0.0.0", "--poort", "8730"]
