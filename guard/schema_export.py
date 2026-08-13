"""Deterministic JSON Schema export for public guard contracts."""

import json
from pathlib import Path

from .contracts import GuardRequest, GuardResult


SCHEMA_FILES = (
    ("guard-request.schema.json", GuardRequest),
    ("guard-result.schema.json", GuardResult),
)


def _serialized_schema(model: type[GuardRequest] | type[GuardResult]) -> str:
    return json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def export_schemas(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for filename, model in SCHEMA_FILES:
        path = output_dir / filename
        path.write_bytes(_serialized_schema(model).encode("utf-8"))
        paths.append(path)
    return paths[0], paths[1]
