# Cardiotic AI — one image for a hospital: web app + server + engine + models. No data leaves the container
# and nothing is downloaded at run time. Build where the internet is available, then move the image into the
# hospital network:  docker save cardiotic:0.1.0 | gzip > cardiotic-0.1.0.tar.gz   ...   docker load < cardiotic-0.1.0.tar.gz
#
# Behind a TLS-inspecting proxy, give the proxy's CA as a build secret (it is used for downloads only and is
# not stored in the image):  docker build --secret id=ca,src=/path/to/proxy-ca.pem --build-arg HTTPS_PROXY=… .
# Base images are pinned by digest so a build next year gives the same image; refresh both on purpose (and rerun the tests):
#   curl -sI https://mirror.gcr.io/v2/library/python/manifests/3.13-slim -H 'Accept: application/vnd.oci.image.index.v1+json' | grep -i docker-content-digest
ARG NODE_IMAGE=node:22-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d
ARG BASE_IMAGE=python:3.13-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc

FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca npm_config_cafile=/run/secrets/ca; fi && npm ci
COPY frontend/ ./
# the static sample data is for demonstrations; the hospital build has none
RUN rm -rf public/data && npm run build

FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CARDIOTIC_ENGINE_THREADS=1 CARDIOTIC_DB=/data/cardiotic.db CARDIOTIC_STATIC=/opt/cardiotic/web
RUN useradd --system --uid 10001 --home-dir /nonexistent cardiotic && mkdir -p /data && chown cardiotic /data
WORKDIR /opt/cardiotic
COPY deploy/requirements.lock deploy/requirements.lock
COPY ml/pyproject.toml ml/README.md ml/
COPY ml/cardiotic_ml ml/cardiotic_ml
COPY engine/pyproject.toml engine/README.md engine/
COPY engine/cardiotic_engine engine/cardiotic_engine
COPY server/pyproject.toml server/README.md server/
COPY server/cardiotic_server server/cardiotic_server
# Third-party packages come from the hashed lock file (exact versions, every file checked); then the product's own packages without
# resolving anything again. pip, setuptools and wheel are brought up to date first (the base image ships older ones with known advisories).
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi && \
    pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --require-hashes -r deploy/requirements.lock && \
    pip install --no-cache-dir --no-deps ./ml ./engine ./server && rm -rf ml engine server deploy
COPY --from=web /web/dist /opt/cardiotic/web
USER cardiotic
VOLUME /data
EXPOSE 8720
# Model integrity is checked at start-up; a changed model file stops the service.
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8720/api/health')"
ENTRYPOINT ["cardiotic-server"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8720"]
