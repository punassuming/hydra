"""The artifact marker both Python workers (full and lite) recognise on a job's stdout.

A job publishes an artifact by printing ``__HYDRA_ARTIFACT__: {"name": "...", "metadata": {...}}``. The line is
consumed (not logged); jobs whose ``triggers_on_artifacts`` lists the name are started with the metadata.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

ARTIFACT_PREFIX = "__HYDRA_ARTIFACT__:"


@dataclass(frozen=True)
class ArtifactMarker:
    valid: bool  # the payload after the prefix was JSON
    name: str = ""  # empty when the JSON had no (or a blank) name
    metadata: Optional[Dict[str, Any]] = None


def parse_artifact_marker(text: str) -> Optional[ArtifactMarker]:
    """``None`` for an ordinary line. For a marker line: ``valid=False`` if the JSON is bad (the caller should log the
    raw line), ``name=""`` if it names nothing (the line is swallowed), else the artifact to publish."""
    stripped = text.strip()
    if not stripped.startswith(ARTIFACT_PREFIX):
        return None
    try:
        payload = json.loads(stripped[len(ARTIFACT_PREFIX) :].strip())
        name = str(payload.get("name") or "").strip()
        metadata = payload.get("metadata") or {}
    except Exception:
        return ArtifactMarker(valid=False)
    return ArtifactMarker(valid=True, name=name, metadata=metadata)
