"""Record contracts for the Eval V1 sample blueprint."""

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Sequence

from .taxonomy import RiskCategory, StringEnum, ToolType


class BlueprintValidationError(ValueError):
    """Raised when blueprint planning data violates its contract."""


class ToolFamily(StringEnum):
    SHELL = "shell"
    POWERSHELL = "powershell"
    CMD = "cmd"
    PYTHON = "python"
    MIXED = "mixed"


class ScenarioKind(StringEnum):
    NORMAL = "normal"
    DANGEROUS = "dangerous"
    BOUNDARY = "boundary"
    INJECTION = "injection"


class AuthoringStatus(StringEnum):
    PLANNED = "planned"


_FIELD_NAMES = {
    "sample_id",
    "tool_family",
    "request_type",
    "scenario_kind",
    "planned_category",
    "scenario",
    "semantic_template",
    "variant",
    "risk_factors",
    "required_context",
    "mixed_components",
    "authoring_status",
}
_SAMPLE_ID_PATTERN = re.compile(r"^EV[0-9]{3}$")
_SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

EXPECTED_TOOL_FAMILIES = Counter(
    {
        ToolFamily.SHELL: 30,
        ToolFamily.POWERSHELL: 20,
        ToolFamily.CMD: 10,
        ToolFamily.PYTHON: 30,
        ToolFamily.MIXED: 10,
    }
)
EXPECTED_SCENARIO_KINDS = Counter(
    {
        ScenarioKind.NORMAL: 40,
        ScenarioKind.DANGEROUS: 34,
        ScenarioKind.BOUNDARY: 16,
        ScenarioKind.INJECTION: 10,
    }
)
EXPECTED_CATEGORIES = Counter(
    {
        RiskCategory.REMOTE_EXECUTION: 8,
        RiskCategory.PRIVILEGE_ESCALATION: 5,
        RiskCategory.DESTRUCTIVE_OPERATION: 7,
        RiskCategory.CREDENTIAL_ACCESS: 5,
        RiskCategory.DATA_EXFILTRATION: 6,
        RiskCategory.PERSISTENCE: 5,
        RiskCategory.DEFENSE_EVASION: 5,
        RiskCategory.UNSAFE_DOWNLOAD: 5,
        RiskCategory.NETWORK_CHANGE: 5,
        RiskCategory.SENSITIVE_WRITE: 5,
        RiskCategory.RESOURCE_ABUSE: 4,
        RiskCategory.BENIGN: 40,
    }
)
EXPECTED_FAMILY_KINDS = Counter(
    {
        (ToolFamily.SHELL, ScenarioKind.NORMAL): 12,
        (ToolFamily.SHELL, ScenarioKind.DANGEROUS): 10,
        (ToolFamily.SHELL, ScenarioKind.BOUNDARY): 5,
        (ToolFamily.SHELL, ScenarioKind.INJECTION): 3,
        (ToolFamily.POWERSHELL, ScenarioKind.NORMAL): 8,
        (ToolFamily.POWERSHELL, ScenarioKind.DANGEROUS): 7,
        (ToolFamily.POWERSHELL, ScenarioKind.BOUNDARY): 3,
        (ToolFamily.POWERSHELL, ScenarioKind.INJECTION): 2,
        (ToolFamily.CMD, ScenarioKind.NORMAL): 4,
        (ToolFamily.CMD, ScenarioKind.DANGEROUS): 3,
        (ToolFamily.CMD, ScenarioKind.BOUNDARY): 2,
        (ToolFamily.CMD, ScenarioKind.INJECTION): 1,
        (ToolFamily.PYTHON, ScenarioKind.NORMAL): 12,
        (ToolFamily.PYTHON, ScenarioKind.DANGEROUS): 10,
        (ToolFamily.PYTHON, ScenarioKind.BOUNDARY): 5,
        (ToolFamily.PYTHON, ScenarioKind.INJECTION): 3,
        (ToolFamily.MIXED, ScenarioKind.NORMAL): 4,
        (ToolFamily.MIXED, ScenarioKind.DANGEROUS): 4,
        (ToolFamily.MIXED, ScenarioKind.BOUNDARY): 1,
        (ToolFamily.MIXED, ScenarioKind.INJECTION): 1,
    }
)


def _error(line_number: int, field: str, message: str) -> BlueprintValidationError:
    return BlueprintValidationError(f"line {line_number}: {field}: {message}")


def _required_string(value: Any, field: str, line_number: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(line_number, field, "must be a nonblank string")
    return value


def _snake_case_string(value: Any, field: str, line_number: int) -> str:
    value = _required_string(value, field, line_number)
    if not _SNAKE_CASE_PATTERN.fullmatch(value):
        raise _error(line_number, field, "must be snake_case")
    return value


def _string_list(value: Any, field: str, line_number: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _error(line_number, field, "must be a list")
    items = tuple(
        _snake_case_string(item, f"{field}[{index}]", line_number)
        for index, item in enumerate(value)
    )
    if len(items) != len(set(items)):
        raise _error(line_number, field, "must not contain duplicates")
    return items


def _enum_value(enum_type, value: Any, field: str, line_number: int):
    if not isinstance(value, str):
        raise _error(line_number, field, "must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise _error(line_number, field, f"invalid value {value!r}") from exc


@dataclass(frozen=True)
class BlueprintRecord:
    sample_id: str
    tool_family: ToolFamily
    request_type: ToolType
    scenario_kind: ScenarioKind
    planned_category: RiskCategory
    scenario: str
    semantic_template: str
    variant: str
    risk_factors: tuple[str, ...]
    required_context: tuple[str, ...]
    mixed_components: tuple[ToolType, ...]
    authoring_status: AuthoringStatus

    @classmethod
    def from_dict(cls, value: object, line_number: int) -> "BlueprintRecord":
        if not isinstance(value, dict):
            raise _error(line_number, "record", "must be a JSON object")

        actual_fields = set(value)
        if actual_fields != _FIELD_NAMES:
            unknown = sorted(actual_fields - _FIELD_NAMES)
            missing = sorted(_FIELD_NAMES - actual_fields)
            details = []
            if unknown:
                details.append(f"unknown fields {unknown}")
            if missing:
                details.append(f"missing fields {missing}")
            raise _error(line_number, "fields", "; ".join(details))

        sample_id = _required_string(value["sample_id"], "sample_id", line_number)
        if not _SAMPLE_ID_PATTERN.fullmatch(sample_id):
            raise _error(line_number, "sample_id", "must match EV followed by three digits")

        tool_family = _enum_value(
            ToolFamily, value["tool_family"], "tool_family", line_number
        )
        request_type = _enum_value(
            ToolType, value["request_type"], "request_type", line_number
        )
        scenario_kind = _enum_value(
            ScenarioKind, value["scenario_kind"], "scenario_kind", line_number
        )
        planned_category = _enum_value(
            RiskCategory,
            value["planned_category"],
            "planned_category",
            line_number,
        )
        authoring_status = _enum_value(
            AuthoringStatus,
            value["authoring_status"],
            "authoring_status",
            line_number,
        )

        raw_components = value["mixed_components"]
        if not isinstance(raw_components, list):
            raise _error(line_number, "mixed_components", "must be a list")
        mixed_components = tuple(
            _enum_value(
                ToolType,
                component,
                f"mixed_components[{index}]",
                line_number,
            )
            for index, component in enumerate(raw_components)
        )
        if len(mixed_components) != len(set(mixed_components)):
            raise _error(line_number, "mixed_components", "must not contain duplicates")
        if tool_family is ToolFamily.MIXED:
            if len(mixed_components) < 2:
                raise _error(
                    line_number,
                    "mixed_components",
                    "mixed samples require at least two components",
                )
            if request_type not in mixed_components:
                raise _error(
                    line_number,
                    "request_type",
                    "must be included in mixed_components",
                )
        elif mixed_components:
            raise _error(
                line_number,
                "mixed_components",
                "must be empty for a single-family sample",
            )
        elif request_type is not ToolType(tool_family.value):
            raise _error(
                line_number,
                "request_type",
                f"must match tool_family {tool_family.value!r}",
            )

        return cls(
            sample_id=sample_id,
            tool_family=tool_family,
            request_type=request_type,
            scenario_kind=scenario_kind,
            planned_category=planned_category,
            scenario=_required_string(value["scenario"], "scenario", line_number),
            semantic_template=_snake_case_string(
                value["semantic_template"], "semantic_template", line_number
            ),
            variant=_snake_case_string(value["variant"], "variant", line_number),
            risk_factors=_string_list(
                value["risk_factors"], "risk_factors", line_number
            ),
            required_context=_string_list(
                value["required_context"], "required_context", line_number
            ),
            mixed_components=mixed_components,
            authoring_status=authoring_status,
        )


@dataclass(frozen=True)
class BlueprintSummary:
    total: int
    tool_families: Counter[ToolFamily]
    scenario_kinds: Counter[ScenarioKind]
    categories: Counter[RiskCategory]

    def to_dict(self) -> dict[str, object]:
        return {
            "categories": dict(
                sorted((key.value, value) for key, value in self.categories.items())
            ),
            "scenario_kinds": dict(
                sorted((key.value, value) for key, value in self.scenario_kinds.items())
            ),
            "tool_families": dict(
                sorted((key.value, value) for key, value in self.tool_families.items())
            ),
            "total": self.total,
        }


def load_blueprint(path: Path) -> list[BlueprintRecord]:
    records = []
    with path.open(encoding="utf-8") as blueprint_file:
        for line_number, line in enumerate(blueprint_file, start=1):
            if not line.strip():
                raise _error(line_number, "record", "blank lines are not allowed")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise _error(line_number, "record", f"invalid JSON: {exc.msg}") from exc
            records.append(BlueprintRecord.from_dict(value, line_number))
    return records


def _quota_error(name: str, actual: Counter, expected: Counter) -> str | None:
    if actual == expected:
        return None
    actual_values = dict(sorted((key.value, value) for key, value in actual.items()))
    expected_values = dict(sorted((key.value, value) for key, value in expected.items()))
    return f"{name} quota mismatch: expected {expected_values}, got {actual_values}"


def _family_kind_quota_error(actual: Counter) -> str | None:
    if actual == EXPECTED_FAMILY_KINDS:
        return None

    def readable(counter: Counter) -> dict[str, int]:
        return dict(
            sorted(
                (f"{family.value}/{kind.value}", count)
                for (family, kind), count in counter.items()
            )
        )

    return (
        "tool_family/scenario_kind quota mismatch: expected "
        f"{readable(EXPECTED_FAMILY_KINDS)}, got {readable(actual)}"
    )


def validate_blueprint(records: Sequence[BlueprintRecord]) -> BlueprintSummary:
    tool_families = Counter(record.tool_family for record in records)
    scenario_kinds = Counter(record.scenario_kind for record in records)
    categories = Counter(record.planned_category for record in records)
    family_kinds_count = Counter(
        (record.tool_family, record.scenario_kind) for record in records
    )
    summary = BlueprintSummary(
        total=len(records),
        tool_families=tool_families,
        scenario_kinds=scenario_kinds,
        categories=categories,
    )
    errors = []

    if len(records) != 100:
        errors.append(f"record count must be 100, got {len(records)}")

    sample_ids = [record.sample_id for record in records]
    duplicate_ids = sorted(
        sample_id for sample_id, count in Counter(sample_ids).items() if count > 1
    )
    if duplicate_ids:
        errors.append(f"duplicate sample_id values: {duplicate_ids}")
    expected_ids = [f"EV{number:03d}" for number in range(1, 101)]
    if sample_ids != expected_ids:
        errors.append("sample_id values must be contiguous EV001 through EV100 in order")

    template_variants = [
        (record.semantic_template, record.variant) for record in records
    ]
    duplicate_pairs = sorted(
        pair for pair, count in Counter(template_variants).items() if count > 1
    )
    if duplicate_pairs:
        errors.append(
            "duplicate semantic_template and variant pairs: "
            f"{duplicate_pairs}"
        )

    duplicate_scenarios = sorted(
        scenario
        for scenario, count in Counter(record.scenario for record in records).items()
        if count > 1
    )
    if duplicate_scenarios:
        errors.append(f"duplicate scenario values: {duplicate_scenarios}")

    for name, actual, expected in (
        ("tool_family", tool_families, EXPECTED_TOOL_FAMILIES),
        ("scenario_kind", scenario_kinds, EXPECTED_SCENARIO_KINDS),
        ("planned_category", categories, EXPECTED_CATEGORIES),
    ):
        quota_error = _quota_error(name, actual, expected)
        if quota_error:
            errors.append(quota_error)

    family_kind_quota_error = _family_kind_quota_error(family_kinds_count)
    if family_kind_quota_error:
        errors.append(family_kind_quota_error)

    family_kinds: dict[ToolFamily, set[ScenarioKind]] = defaultdict(set)
    category_families: dict[RiskCategory, set[ToolFamily]] = defaultdict(set)
    for record in records:
        family_kinds[record.tool_family].add(record.scenario_kind)
        category_families[record.planned_category].add(record.tool_family)
        if (
            record.scenario_kind is ScenarioKind.NORMAL
            and record.planned_category is not RiskCategory.BENIGN
        ):
            errors.append(
                f"{record.sample_id}: normal samples must use benign category"
            )
        if (
            record.scenario_kind is not ScenarioKind.NORMAL
            and record.planned_category is RiskCategory.BENIGN
        ):
            errors.append(
                f"{record.sample_id}: non-normal samples must use a non-benign category"
            )

    for family in ToolFamily:
        for kind in ScenarioKind:
            if kind not in family_kinds[family]:
                errors.append(
                    f"tool family {family.value} must include scenario kind {kind.value}"
                )

    for category in RiskCategory:
        if category is RiskCategory.BENIGN:
            continue
        if len(category_families[category]) < 2:
            errors.append(
                f"category {category.value} must span at least two tool families"
            )

    if errors:
        raise BlueprintValidationError("blueprint validation failed:\n- " + "\n- ".join(errors))
    return summary
