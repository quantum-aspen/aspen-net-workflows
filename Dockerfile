# One container: Dagu (server + scheduler), the step commands and the meeting scripts with
# their toolchain, and Hermes for the agent step. Built on the Hermes image, as
# aspen-net-transcriber is, so its s6 init still drops to the hermes user and reaps orphans.
ARG HERMES_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_IMAGE}

ARG DAGU_VERSION=2.24.0

USER root
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg jq curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://github.com/dagu-org/dagu/releases/download/v${DAGU_VERSION}/dagu_${DAGU_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin dagu

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv
WORKDIR /opt/workflows
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra media
ENV PATH=/opt/workflows/.venv/bin:$PATH VIRTUAL_ENV=/opt/workflows/.venv

COPY dags ./dags
COPY dagu.yaml /opt/dagu/config.yaml
COPY base.yaml /opt/dagu/base.yaml
# COPY keeps the build context's modes, and a checkout made with a strict umask has 0600
# files that the hermes user, which runs everything, can't read.
RUN chmod -R a+rX src dags README.md pyproject.toml /opt/dagu

# Dagu's home is in the image, so every dagu command finds its config.yaml (this repo's
# dagu.yaml; a deployment can mount its own over it). Its state goes on the data volume.
ENV DAGU_HOME=/opt/dagu \
    DAGU_DAGS_DIR=/opt/workflows/dags \
    DAGU_DATA_DIR=/opt/data/dagu/data \
    DAGU_LOG_DIR=/opt/data/dagu/logs \
    DAGU_ADMIN_LOG_DIR=/opt/data/dagu/logs/admin \
    DAGU_EVENT_STORE_DIR=/opt/data/dagu/logs/admin/events \
    DAGU_WIKI_DIR=/opt/data/dagu/wiki \
    DATA_DIR=/opt/data \
    DAGU_COORDINATOR_ENABLED=false

# Hermes' config (Lumen, no MCP servers) is written by the summarise step, from the env.
CMD ["dagu", "start-all", "--host", "0.0.0.0", "--port", "8080"]
