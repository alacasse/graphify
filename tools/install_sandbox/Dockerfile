FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/graphify-home \
    XDG_CONFIG_HOME=/tmp/graphify-home/.config \
    GRAPHIFY_PROJECT=/tmp/graphify-project \
    GRAPHIFY_REPO_MOUNT=/mnt/graphify-repo \
    GRAPHIFY_SRC=/tmp/graphify-src \
    GRAPHIFY_OUTPUT=/sandbox-out \
    PYTHONPATH=/runner

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

RUN python -m pip install "PyYAML>=6.0.3"

RUN mkdir -p /runner/tools/install_sandbox /tmp/graphify-home/.config /tmp/graphify-project /sandbox-out \
    && touch /runner/tools/__init__.py \
    && chmod -R 0777 /tmp/graphify-home /tmp/graphify-project /sandbox-out

WORKDIR /runner

COPY . /runner/tools/install_sandbox/

ENTRYPOINT ["python", "-m", "tools.install_sandbox.sandbox_runner"]
