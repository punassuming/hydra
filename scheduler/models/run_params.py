"""Run-parameter validation shared by the full and lite APIs.

Run params become environment variables, so keys must be valid variable names.
Keep in sync with cli/__main__.py (PARAM_KEY_PATTERN, dependency-free copy) and ui/src/utils/params.ts.
"""

import re
from typing import Dict

from pydantic import BaseModel, field_validator

PARAM_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PARAM_KEY_MAX_LENGTH = 128


class RunJobRequest(BaseModel):
    params: Dict[str, str] = {}

    @field_validator("params")
    @classmethod
    def _validate_param_keys(cls, params: Dict[str, str]) -> Dict[str, str]:
        for key in params:
            if len(key) > PARAM_KEY_MAX_LENGTH or not PARAM_KEY_PATTERN.match(key):
                raise ValueError(
                    f"invalid param name {key!r}: must match {PARAM_KEY_PATTERN.pattern} "
                    f"and be at most {PARAM_KEY_MAX_LENGTH} characters"
                )
        return params
