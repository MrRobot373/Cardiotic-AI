# Cardiotic AI — one image for a hospital: web app + server + engine + models. No data leaves the container
# and nothing is downloaded at run time. Build where the internet is available, then move the image into the
# hospital network:  docker save cardiotic:0.1.0 | gzip > cardiotic-0.1.0.tar.gz   ...   docker load < cardiotic-0.1.0.tar.gz
#
# Behind a TLS-inspecting proxy, give the proxy's CA as a build secret (it is used for downloads only and is
# not stored in the image):  docker build --secret id=ca,src=/path/to/proxy-ca.pem --build-arg HTTPS_PROXY=… .
ARG NODE_IMAGE=node:22-slim
ARG BASE_IMAGE=python:3.12-slim

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
COPY ml/pyproject.toml ml/README.md ml/
COPY ml/cardiotic_ml ml/cardiotic_ml
COPY engine/pyproject.toml engine/README.md engine/
COPY engine/cardiotic_engine engine/cardiotic_engine
COPY server/pyproject.toml server/README.md server/
COPY server/cardiotic_server server/cardiotic_server
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi && \
    pip install --no-cache-dir ./ml ./engine ./server && rm -rf ml engine server
COPY --from=web /web/dist /opt/cardiotic/web
USER cardiotic
VOLUME /data
EXPOSE 8720
# Model integrity is checked at start-up; a changed model file stops the service.
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8720/api/health')"
ENTRYPOINT ["cardiotic-server"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8720"]
