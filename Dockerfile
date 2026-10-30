# SKETCH — not built yet. One container: Dagu (server + scheduler), the step commands,
# the skill's scripts and toolchain, and Hermes for the agent step. Built on the Hermes
# image, as aspen-net-transcriber is, so its s6 init still drops to the hermes user and
# reaps orphans.
ARG HERMES_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_IMAGE}

ARG DAGU_VERSION=2.24.0
ARG SKILLS_REF=main

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

ADD https://github.com/quantum-aspen/aspen-net-skills.git#${SKILLS_REF}:skills /opt/skills
COPY dags ./dags
COPY dagu.yaml /opt/dagu-config.yaml

ENV DAGU_HOME=/opt/data/dagu \
    DAGU_DAGS_DIR=/opt/workflows/dags \
    DATA_DIR=/opt/data \
    SKILL_DIR=/opt/skills/local-meeting-transcript \
    DAGU_COORDINATOR_ENABLED=false

# TODO: install /opt/dagu-config.yaml as $DAGU_HOME/config.yaml at start, write Hermes'
# config (Lumen, no MCP servers), and run `dagu start-all --host 0.0.0.0` as hermes.
CMD ["dagu", "start-all", "--host", "0.0.0.0", "--port", "8080"]
