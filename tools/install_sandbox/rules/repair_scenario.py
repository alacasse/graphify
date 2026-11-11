"""Prepare a bounded mutation and independent transition expectations without effects."""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import ClassVar

from tools.install_sandbox.contracts.bound_mutation import (
    BoundFileAppend,
    BoundFileCreation,
    BoundFileRemoval,
    BoundFileReplacement,
    BoundMarkdownMutation,
    BoundMutation,
    BoundStaleReferencesTmpCreation,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase, seeded_json_hook_group
from tools.install_sandbox.contracts.effects import (
    Destination,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.expectations import (
    Expectation,
    ExpectationSet,
)
from tools.install_sandbox.contracts.intermediate import (
    STALE_REFERENCE_CONTENT,
    AlteredReferencePreparation,
    AlteredSkillPreparation,
    IntermediatePreparation,
    JsonHookPreparation,
    MissingReferencePreparation,
    PreserveSkillBackupPreparation,
    StaleReferencePreparation,
    StaleReferencesTmpPreparation,
    StaleVersionPreparation,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import VerificationResult
from tools.install_sandbox.rules.comparison import markdown_byte_parts, read_json
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    preservation_baseline,
    retained_bytes,
    selected_reference,
    selected_skill,
    selected_stale_reference,
    selected_version,
)
from tools.install_sandbox.rules.json_hook_repair import (
    prepared_hook_settings,
    target_group_preserved,
)


@dataclass(frozen=True)
class PreparationBlocked:
    reason: str


@dataclass(frozen=True)
class PreparationPlan:
    operation: BoundMutation
    after_preparation_expectations: ExpectationSet
    second_install_expectations: ExpectationSet


def _conforming(validation: VerificationResult) -> bool:
    return validation.complete and not validation.mismatches and not validation.obstacles


def _validate_first_install(
    case: EffectInstallCase,
    case_bytes: bytes,
    installed: ExpectationSet,
    first_after: FilesystemSnapshot,
    validation: VerificationResult,
) -> None:
    if EffectInstallCase.from_json(case_bytes.decode("utf-8")) != case:
        raise ValueError("Archived case differs from unchanged case definition")
    if installed.phase != "install" or installed.roots is None:
        raise ValueError("Preparation requires bound first-install expectations")
    actual = EffectVerifier().verify(installed, first_after)
    if not _conforming(validation) or not _conforming(actual) or validation != actual:
        raise ValueError("Preparation requires a conforming verdict for this observation")


def _transition(
    installed: ExpectationSet,
    first_after: FilesystemSnapshot,
    replacements: tuple[Expectation, ...],
    phase: str,
) -> ExpectationSet:
    by_destination = {(item.root, item.path): item for item in replacements}
    if len(by_destination) != len(replacements):
        raise ValueError("Duplicate transition replacement")
    existing = {(item.root, item.path) for item in installed.expectations}
    if not by_destination.keys() <= existing:
        raise ValueError("Transition replacement requires an explicit prior constraint")
    constraints = tuple(
        by_destination.get((item.root, item.path), replace(item, phase=phase))
        for item in installed.expectations
    )
    return replace(
        installed,
        phase=phase,
        expectations=constraints,
        baseline=preservation_baseline(first_after, phase),
        allowed_changes=tuple(by_destination),
    )


@dataclass(frozen=True)
class MarkdownRepairScenario(ABC):
    """Own the applicable scenario and authorize binding to validated facts."""

    case: EffectInstallCase
    sources: FilesystemSnapshot
    provenance: ClassVar[str]

    @abstractmethod
    def mutation(
        self, parts: tuple[bytes, bytes, bytes], document: bytes
    ) -> tuple[int, int, bytes]: ...

    @abstractmethod
    def expected_preparation(self) -> bytes: ...

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            if EffectInstallCase.from_json(case_bytes.decode("utf-8")) != self.case:
                raise ValueError("Archived case differs from the unchanged case definition")
            if installed.phase != "install" or installed.roots is None:
                raise ValueError("Preparation requires bound first-install expectations")
            actual = EffectVerifier().verify(installed, first_after)
            if not _conforming(validation) or not _conforming(actual) or validation != actual:
                raise ValueError("Preparation requires a conforming verdict for this observation")
            return self._build_bound(first_after, observation_ref, installed, case_bytes)
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))

    def _build_bound(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan:
        case, sources = self.case, self.sources
        preparation = case.intermediate_preparation
        if not isinstance(preparation, IntermediatePreparation):
            raise ValueError("Case has no Markdown preparation")
        destination = preparation.destination
        document = retained_bytes(first_after, destination.root, destination.path)
        parts = markdown_byte_parts(document, preparation.marker)
        if parts is None:
            raise ValueError("Validated document has no unique section")
        effect = next(
            e
            for e in case.effects.effects
            if isinstance(e, MarkdownSectionEffect) and e.destination == destination
        )
        source = retained_bytes(sources, "subject", effect.source)
        if document != preparation.before + source + preparation.after:
            raise ValueError("First installation differs from exact retained fragments and source")
        exterior = preparation.before + preparation.after
        start, end, replacement = self.mutation(parts, document)
        expected = self.expected_preparation()
        removed = Expectation(
            "file",
            destination.root,
            destination.path,
            "intermediate",
            self.provenance,
            expected,
        )
        repaired = Expectation(
            "markdown-composed",
            destination.root,
            destination.path,
            "reinstall",
            "case:fragments+source",
            source,
            exterior,
            preparation.marker,
        )
        operation = BoundMarkdownMutation(
            hashlib.sha256(case_bytes).hexdigest(),
            observation_ref,
            destination,
            hashlib.sha256(document).hexdigest(),
            start,
            end,
            replacement,
        )
        return PreparationPlan(
            operation,
            _transition(installed, first_after, (removed,), "intermediate"),
            _transition(installed, first_after, (repaired,), "reinstall"),
        )


@dataclass(frozen=True)
class MissingSectionScenario(MarkdownRepairScenario):
    provenance = "case:fragments"

    def mutation(self, parts: tuple[bytes, bytes, bytes], document: bytes):
        return len(parts[0]), len(parts[0]) + len(parts[1]), b""

    def expected_preparation(self) -> bytes:
        preparation = self.case.intermediate_preparation
        assert isinstance(preparation, IntermediatePreparation)
        return preparation.before + preparation.after


@dataclass(frozen=True)
class AlteredBodyScenario(MarkdownRepairScenario):
    provenance = "case:fragments+marker+body"
    altered_body: bytes

    def mutation(self, parts: tuple[bytes, bytes, bytes], document: bytes):
        preparation = self.case.intermediate_preparation
        assert isinstance(preparation, IntermediatePreparation)
        header = preparation.marker.encode("utf-8") + b"\n"
        if not parts[1].startswith(header):
            raise ValueError("Section has no applicable LF-terminated body")
        start, end = len(parts[0]) + len(header), len(parts[0]) + len(parts[1])
        if start >= end or document[start:end] == self.altered_body:
            raise ValueError("Preparation must change an applicable section body")
        return start, end, self.altered_body

    def expected_preparation(self) -> bytes:
        preparation = self.case.intermediate_preparation
        assert isinstance(preparation, IntermediatePreparation)
        return (
            preparation.before
            + preparation.marker.encode("utf-8")
            + b"\n"
            + self.altered_body
            + preparation.after
        )


@dataclass(frozen=True)
class MissingReferenceScenario:
    case: EffectInstallCase
    sources: FilesystemSnapshot

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            _validate_first_install(self.case, case_bytes, installed, first_after, validation)
            destination = selected_reference(self.case, self.sources)
            content = retained_bytes(first_after, destination.root, destination.path)
            key = destination.root, destination.path
            absent = Expectation("absent", *key, "intermediate", "case:missing-reference")
            intermediate = replace(
                _transition(installed, first_after, (absent,), "intermediate"),
                allowed_changes=(),
                allowed_removals=(key,),
            )
            restored = replace(
                installed.in_phase("reinstall"),
                allowed_changes=(key,),
                baseline=preservation_baseline(first_after, "reinstall"),
            )
            operation = BoundFileRemoval(
                hashlib.sha256(case_bytes).hexdigest(),
                observation_ref,
                destination,
                hashlib.sha256(content).hexdigest(),
            )
            operation.verify_binding(case_bytes, first_after)
            return PreparationPlan(operation, intermediate, restored)
        except (ValueError, UnicodeError) as exc:
            return PreparationBlocked(str(exc))


@dataclass(frozen=True)
class AlteredReferenceScenario:
    case: EffectInstallCase
    sources: FilesystemSnapshot

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            _validate_first_install(self.case, case_bytes, installed, first_after, validation)
            preparation = self.case.intermediate_preparation
            if not isinstance(preparation, AlteredReferencePreparation):
                raise ValueError("Case has no altered reference preparation")
            preparation.to_data()
            destination = selected_reference(self.case, self.sources)
            key = destination.root, destination.path
            effect = next(
                effect
                for effect in self.case.effects.effects
                if isinstance(effect, SkillEffect) and effect.destination == preparation.destination
            )
            relative = destination.path.removeprefix(effect.destination.path + "/references/")
            source_path = effect.references + "/" + relative
            source = retained_bytes(self.sources, "subject", source_path)
            if retained_bytes(first_after, *key) != source:
                raise ValueError("First reference differs from retained source")
            altered = Expectation(
                "file", *key, "intermediate", "case:source+suffix", source + preparation.suffix
            )
            restored = Expectation(
                "file", *key, "reinstall", "source:subject:" + source_path, source
            )
            operation = BoundFileAppend(
                hashlib.sha256(case_bytes).hexdigest(),
                observation_ref,
                destination,
                hashlib.sha256(source).hexdigest(),
                preparation.suffix,
            )
            operation.verify_binding(case_bytes, first_after)
            return PreparationPlan(
                operation,
                _transition(installed, first_after, (altered,), "intermediate"),
                _transition(installed, first_after, (restored,), "reinstall"),
            )
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))


@dataclass(frozen=True)
class AlteredSkillScenario:
    case: EffectInstallCase
    sources: FilesystemSnapshot

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            _validate_first_install(self.case, case_bytes, installed, first_after, validation)
            preparation = self.case.intermediate_preparation
            if not isinstance(preparation, AlteredSkillPreparation):
                raise ValueError("Case has no altered skill preparation")
            destination = selected_skill(self.case)
            key = destination.root, destination.path
            effect = next(
                effect
                for effect in self.case.effects.effects
                if isinstance(effect, SkillEffect) and effect.destination == preparation.destination
            )
            source = retained_bytes(self.sources, "subject", effect.source)
            if retained_bytes(first_after, *key) != source:
                raise ValueError("First skill differs from retained source")
            changed = source + preparation.suffix
            altered = Expectation("file", *key, "intermediate", "case:source+suffix", changed)
            restored = Expectation(
                "file", *key, "reinstall", "source:subject:" + effect.source, source
            )
            backup = Expectation(
                "file",
                destination.root,
                destination.path + self.case.subject.rules.skill_backup,
                "reinstall",
                "case:source+suffix",
                changed,
            )
            operation = BoundFileAppend(
                hashlib.sha256(case_bytes).hexdigest(),
                observation_ref,
                destination,
                hashlib.sha256(source).hexdigest(),
                preparation.suffix,
            )
            operation.verify_binding(case_bytes, first_after)
            return PreparationPlan(
                operation,
                _transition(installed, first_after, (altered,), "intermediate"),
                _transition(installed, first_after, (restored, backup), "reinstall"),
            )
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))


@dataclass(frozen=True)
class StaleVersionScenario:
    case: EffectInstallCase
    sources: FilesystemSnapshot

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            _validate_first_install(self.case, case_bytes, installed, first_after, validation)
            destination, expected, witness = selected_version(self.case, self.sources)
            key = destination.root, destination.path
            if retained_bytes(first_after, *key) != expected:
                raise ValueError("First installed version differs from retained metadata")
            stale = Expectation("file", *key, "intermediate", "case:stale-version-witness", witness)
            restored = Expectation(
                "file",
                *key,
                "reinstall",
                "version:subject:" + self.case.subject.version_source,
                expected,
            )
            operation = BoundFileReplacement(
                hashlib.sha256(case_bytes).hexdigest(),
                observation_ref,
                destination,
                hashlib.sha256(expected).hexdigest(),
                witness,
            )
            operation.verify_binding(case_bytes, first_after)
            return PreparationPlan(
                operation,
                _transition(installed, first_after, (stale,), "intermediate"),
                _transition(installed, first_after, (restored,), "reinstall"),
            )
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))


@dataclass(frozen=True)
class StaleReferenceScenario:
    case: EffectInstallCase
    sources: FilesystemSnapshot

    def _witnesses(
        self, case_digest: str, observation_ref: str
    ) -> tuple[BoundFileCreation, tuple[Expectation, ...]]:
        preparation = self.case.intermediate_preparation
        if isinstance(preparation, StaleReferencesTmpPreparation):
            directory = preparation.directory_destination
            destination = preparation.witness_destination
            operation = BoundStaleReferencesTmpCreation(
                case_digest, observation_ref, destination, STALE_REFERENCE_CONTENT
            )
            return operation, (
                Expectation(
                    "directory",
                    directory.root,
                    directory.path,
                    "intermediate",
                    "rule:references_tmp",
                ),
                Expectation(
                    "file",
                    destination.root,
                    destination.path,
                    "intermediate",
                    "case:stale-references-tmp-witness",
                    STALE_REFERENCE_CONTENT,
                ),
            )
        destination, _ = selected_stale_reference(self.case, self.sources)
        return BoundFileCreation(
            case_digest, observation_ref, destination, STALE_REFERENCE_CONTENT
        ), (
            Expectation(
                "file",
                destination.root,
                destination.path,
                "intermediate",
                "case:stale-reference-witness",
                STALE_REFERENCE_CONTENT,
            ),
        )

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            _validate_first_install(self.case, case_bytes, installed, first_after, validation)
            operation, additions = self._witnesses(
                hashlib.sha256(case_bytes).hexdigest(), observation_ref
            )
            operation.verify_binding(case_bytes, first_after)
            intermediate = _transition(installed, first_after, additions, "intermediate")
            repaired = replace(
                installed.in_phase("reinstall"),
                allowed_changes=(),
                baseline=(
                    *preservation_baseline(first_after, "reinstall"),
                    *(replace(item, phase="reinstall") for item in additions),
                ),
                allowed_removals=tuple((item.root, item.path) for item in additions),
            )
            return PreparationPlan(operation, intermediate, repaired)
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))


@dataclass(frozen=True)
class PreserveSkillBackupScenario:
    case: EffectInstallCase
    sources: FilesystemSnapshot

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            _validate_first_install(self.case, case_bytes, installed, first_after, validation)
            preparation = self.case.intermediate_preparation
            if not isinstance(preparation, PreserveSkillBackupPreparation):
                raise ValueError("Case has no preserved skill backup preparation")
            skill = selected_skill(self.case)
            effect = next(
                effect
                for effect in self.case.effects.effects
                if isinstance(effect, SkillEffect) and effect.destination == preparation.destination
            )
            source = retained_bytes(self.sources, "subject", effect.source)
            if retained_bytes(first_after, skill.root, skill.path) != source:
                raise ValueError("First skill differs from retained source")
            destination = Destination(skill.root, skill.path + self.case.subject.rules.skill_backup)
            content = source + preparation.suffix
            backup = Expectation(
                "file",
                destination.root,
                destination.path,
                "intermediate",
                "case:source+suffix",
                content,
            )
            operation = BoundFileCreation(
                hashlib.sha256(case_bytes).hexdigest(),
                observation_ref,
                destination,
                content,
            )
            operation.verify_binding(case_bytes, first_after)
            return PreparationPlan(
                operation,
                replace(
                    _transition(installed, first_after, (backup,), "intermediate"),
                    allowed_removals=(),
                ),
                replace(
                    _transition(
                        installed, first_after, (replace(backup, phase="reinstall"),), "reinstall"
                    ),
                    allowed_changes=(),
                    allowed_removals=(),
                ),
            )
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))


@dataclass(frozen=True)
class JsonHookRepairScenario:
    case: EffectInstallCase
    sources: FilesystemSnapshot

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            _validate_first_install(self.case, case_bytes, installed, first_after, validation)
            preparation = self.case.intermediate_preparation
            if not isinstance(preparation, JsonHookPreparation):
                raise ValueError("Case has no JSON hook preparation")
            effect = next(
                e
                for e in self.case.effects.effects
                if isinstance(e, JsonHooksEffect) and e.effect_id == preparation.effect_id
            )
            target = next(hook for hook in effect.hooks if hook.id == preparation.member)
            if preparation.destination != effect.destination:
                raise ValueError("Preparation destination differs from its declared effect")
            if (
                self.case.key.effect_id != effect.effect_id
                or self.case.key.member != target.id
                or self.case.key.operation != preparation.kind
            ):
                raise ValueError("Preparation target differs from the bound case key")
            destination = effect.destination
            document = retained_bytes(first_after, destination.root, destination.path)
            parsed = read_json(document)
            seeded: dict[str, object] = {
                "hooks": {target.event: [seeded_json_hook_group(effect, target)]}
            }
            if not target_group_preserved(seeded, parsed, target):
                raise ValueError("Target hook must remain in its intact seeded personal group")
            prepared = prepared_hook_settings(
                replace(effect, hooks=(target,)), document, preparation.kind
            )
            if preparation.kind == "missing-json-hook":
                kind, provenance = "json-hook-removed", "observation:remove-declared-hook"
            elif preparation.kind == "altered-json-hook":
                kind, provenance = "json-hook-altered", "observation:alter-declared-hook-timeout"
            elif preparation.kind == "duplicate-json-hook":
                kind, provenance = "json-hook-duplicated", "observation:duplicate-declared-hook"
            else:
                raise ValueError("Unsupported JSON hook preparation")
            intermediate = Expectation(
                kind,
                destination.root,
                destination.path,
                "intermediate",
                provenance,
                baseline=document,
                hooks=(target,),
            )
            repaired = Expectation(
                "json-hook-repair",
                destination.root,
                destination.path,
                "reinstall",
                "observation:prepared-json+declared-hook",
                baseline=document,
                hooks=(target,),
            )
            operation = BoundFileReplacement(
                hashlib.sha256(case_bytes).hexdigest(),
                observation_ref,
                destination,
                hashlib.sha256(document).hexdigest(),
                prepared,
                target=self.case.key,
            )
            operation.verify_binding(case_bytes, first_after)
            return PreparationPlan(
                operation,
                _transition(installed, first_after, (intermediate,), "intermediate"),
                _transition(installed, first_after, (repaired,), "reinstall"),
            )
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))


def repair_scenario_from_case(
    case: EffectInstallCase, sources: FilesystemSnapshot
) -> (
    MarkdownRepairScenario
    | MissingReferenceScenario
    | AlteredReferenceScenario
    | AlteredSkillScenario
    | PreserveSkillBackupScenario
    | StaleVersionScenario
    | StaleReferenceScenario
    | JsonHookRepairScenario
):
    preparation = case.intermediate_preparation
    if preparation is None:
        raise ValueError("Case has no intermediate preparation")
    scenarios: dict[
        type[object],
        type[MissingReferenceScenario]
        | type[AlteredReferenceScenario]
        | type[AlteredSkillScenario]
        | type[PreserveSkillBackupScenario]
        | type[StaleVersionScenario]
        | type[StaleReferenceScenario]
        | type[JsonHookRepairScenario],
    ] = {
        MissingReferencePreparation: MissingReferenceScenario,
        JsonHookPreparation: JsonHookRepairScenario,
        AlteredReferencePreparation: AlteredReferenceScenario,
        AlteredSkillPreparation: AlteredSkillScenario,
        PreserveSkillBackupPreparation: PreserveSkillBackupScenario,
        StaleVersionPreparation: StaleVersionScenario,
        StaleReferencePreparation: StaleReferenceScenario,
        StaleReferencesTmpPreparation: StaleReferenceScenario,
    }
    scenario = scenarios.get(type(preparation))
    if scenario is not None:
        return scenario(case, sources)
    if not isinstance(preparation, IntermediatePreparation):
        raise ValueError("Unsupported repair scenario")
    if preparation.kind == "missing-markdown-section":
        return MissingSectionScenario(case, sources)
    if preparation.kind == "altered-markdown-body":
        if not isinstance(preparation.body, bytes):
            raise ValueError("Altered scenario requires body bytes")
        return AlteredBodyScenario(case, sources, preparation.body)
    raise ValueError("Unsupported repair scenario")
