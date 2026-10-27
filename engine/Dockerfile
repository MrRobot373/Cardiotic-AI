# Cardiotic AI engine — offline on-premise image. Build where internet is available, then move the image
# to the hospital network (docker save / docker load). No data leaves the container; nothing is downloaded at run time.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CARDIOTIC_ENGINE_THREADS=1
RUN useradd --system --uid 10001 engine
WORKDIR /opt/cardiotic
COPY ml/pyproject.toml ml/README.md ml/
COPY ml/cardiotic_ml ml/cardiotic_ml
COPY engine/pyproject.toml engine/README.md engine/
COPY engine/cardiotic_engine engine/cardiotic_engine
RUN pip install --no-cache-dir ./ml ./engine && rm -rf ml engine
USER engine
EXPOSE 8710
# Model integrity is checked at start-up; a changed model file stops the service.
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8710/v1/health')"
CMD ["cardiotic-engine", "serve", "--host", "0.0.0.0", "--port", "8710"]
