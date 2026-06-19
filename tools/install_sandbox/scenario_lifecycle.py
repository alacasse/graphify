from __future__ import annotations

try:
    from . import validation_plan
    from .scenario_lifecycle_disposable import (
        DisposableArtifactLifecycle,
        disposable_artifact_scenarios,
        run_disposable_artifact_scenario,
        run_purge_scenario,
    )
    from .scenario_lifecycle_support import (
        CommandExecutor,
        DisposableArtifactOutcome,
        MatrixRunnerOverrides,
        SandboxPaths,
        ScenarioArtifacts,
        ScenarioFileEffects,
        ScenarioLifecycleHooks,
        ScenarioResultOutcome,
        ScenarioRunContext,
        StandardScenarioOutcome,
        StandardScenarioStages,
        UniversalUninstallOutcome,
        prepare_scenario_run,
        scenario_artifact_dir,
        scenario_duration_ms,
    )
    from .scenario_lifecycle_standard import (
        INITIAL_INSTALL_PHASE,
        REPEAT_INSTALL_PHASE,
        STALE_SIDECAR_REPAIR_PHASE,
        UNINSTALL_PHASE,
        StandardLifecycleMechanics,
        StandardLifecyclePhase,
        finalize_standard_scenario,
        run_equivalence_stage,
        run_initial_install,
        run_repeat_install,
        run_scenario,
        run_stale_sidecar_repair,
        run_uninstall_stage,
        standard_scenario_checks,
        standard_scenario_command_ok,
    )
    from .scenario_lifecycle_plan import (
        _positional_parameter_count,
        _run_purge_override,
        _run_universal_override,
        run_matrix_scenarios,
        run_validation_plan,
    )
    from .scenario_lifecycle_universal import (
        UniversalUninstallLifecycle,
        run_universal_uninstall_scenario,
        universal_uninstall_spec_for_scope,
    )
    from .platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario
except ImportError:
    import validation_plan  # type: ignore[no-redef]
    from scenario_lifecycle_disposable import (  # type: ignore[no-redef]
        DisposableArtifactLifecycle,
        disposable_artifact_scenarios,
        run_disposable_artifact_scenario,
        run_purge_scenario,
    )
    from scenario_lifecycle_support import (  # type: ignore[no-redef]
        CommandExecutor,
        DisposableArtifactOutcome,
        MatrixRunnerOverrides,
        SandboxPaths,
        ScenarioArtifacts,
        ScenarioFileEffects,
        ScenarioLifecycleHooks,
        ScenarioResultOutcome,
        ScenarioRunContext,
        StandardScenarioOutcome,
        StandardScenarioStages,
        UniversalUninstallOutcome,
        prepare_scenario_run,
        scenario_artifact_dir,
        scenario_duration_ms,
    )
    from scenario_lifecycle_standard import (  # type: ignore[no-redef]
        INITIAL_INSTALL_PHASE,
        REPEAT_INSTALL_PHASE,
        STALE_SIDECAR_REPAIR_PHASE,
        UNINSTALL_PHASE,
        StandardLifecycleMechanics,
        StandardLifecyclePhase,
        finalize_standard_scenario,
        run_equivalence_stage,
        run_initial_install,
        run_repeat_install,
        run_scenario,
        run_stale_sidecar_repair,
        run_uninstall_stage,
        standard_scenario_checks,
        standard_scenario_command_ok,
    )
    from scenario_lifecycle_plan import (  # type: ignore[no-redef]
        _positional_parameter_count,
        _run_purge_override,
        _run_universal_override,
        run_matrix_scenarios,
        run_validation_plan,
    )
    from scenario_lifecycle_universal import (  # type: ignore[no-redef]
        UniversalUninstallLifecycle,
        run_universal_uninstall_scenario,
        universal_uninstall_spec_for_scope,
    )
    from platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario
