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

RUN python -m pip install "PyYAML>=6.0.3"

RUN mkdir -p /runner /tmp/graphify-home/.config /tmp/graphify-project /sandbox-out \
    && chmod -R 0777 /tmp/graphify-home /tmp/graphify-project /sandbox-out

WORKDIR /runner

COPY sandbox_runner.py /runner/sandbox_runner.py
COPY agent_summary.py /runner/agent_summary.py
COPY command_runner.py /runner/command_runner.py
COPY expected_effects.py /runner/expected_effects.py
COPY file_effect_generated_artifacts.py /runner/file_effect_generated_artifacts.py
COPY file_effect_oracle.py /runner/file_effect_oracle.py
COPY file_effect_sidecars.py /runner/file_effect_sidecars.py
COPY file_effect_state.py /runner/file_effect_state.py
COPY file_effect_surfaces.py /runner/file_effect_surfaces.py
COPY file_walk.py /runner/file_walk.py
COPY harness_specs.py /runner/harness_specs.py
COPY install_surface_core.py /runner/install_surface_core.py
COPY install_surface_generated.py /runner/install_surface_generated.py
COPY install_surface_sidecars.py /runner/install_surface_sidecars.py
COPY install_surface_state.py /runner/install_surface_state.py
COPY install_surface_statuses.py /runner/install_surface_statuses.py
COPY json_helpers.py /runner/json_helpers.py
COPY platform_specs.py /runner/platform_specs.py
COPY spec_loader.py /runner/spec_loader.py
COPY specs /runner/specs
COPY reference_resolution.py /runner/reference_resolution.py
COPY reports.py /runner/reports.py
COPY scenario_file_effects_adapter.py /runner/scenario_file_effects_adapter.py
COPY scenario_lifecycle.py /runner/scenario_lifecycle.py
COPY scenario_lifecycle_support.py /runner/scenario_lifecycle_support.py
COPY scenario_lifecycle_standard.py /runner/scenario_lifecycle_standard.py
COPY source_snapshot.py /runner/source_snapshot.py
COPY status.py /runner/status.py
COPY validation_plan.py /runner/validation_plan.py

ENTRYPOINT ["python", "/runner/sandbox_runner.py"]
