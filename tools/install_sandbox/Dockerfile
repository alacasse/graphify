FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/graphify-home \
    XDG_CONFIG_HOME=/tmp/graphify-home/.config \
    GRAPHIFY_PROJECT=/tmp/graphify-project \
    GRAPHIFY_REPO_MOUNT=/mnt/graphify-repo \
    GRAPHIFY_SRC=/tmp/graphify-src \
    GRAPHIFY_OUTPUT=/sandbox-out

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        curl \
        findutils \
        git \
        jq \
        nodejs \
        npm \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /runner /tmp/graphify-home/.config /tmp/graphify-project /sandbox-out \
    && chmod -R 0777 /tmp/graphify-home /tmp/graphify-project /sandbox-out

WORKDIR /runner

COPY sandbox_runner.py /runner/sandbox_runner.py
COPY command_runner.py /runner/command_runner.py
COPY file_effects.py /runner/file_effects.py
COPY platform_specs.py /runner/platform_specs.py
COPY reports.py /runner/reports.py
COPY scenario_lifecycle.py /runner/scenario_lifecycle.py
COPY source_snapshot.py /runner/source_snapshot.py

ENTRYPOINT ["python", "/runner/sandbox_runner.py"]
