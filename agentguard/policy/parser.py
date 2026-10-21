"""Load a YAML policy file into ordered PolicyRule objects."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import PolicyRule


class PolicyParseError(ValueError):
    """Raised when a policy file is missing, malformed, or self-contradictory."""


def load_policies(path: str | Path) -> list[PolicyRule]:
    path = Path(path)
    if not path.exists():
        raise PolicyParseError(f"Policy file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise PolicyParseError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict) or "policies" not in raw:
        raise PolicyParseError(f"{path}: expected top-level 'policies:' key")
    entries = raw["policies"]
    if not isinstance(entries, list) or not entries:
        raise PolicyParseError(f"{path}: 'policies:' must be a non-empty list")
    rules: list[PolicyRule] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise PolicyParseError(f"{path}: policies[{i}] must be a mapping")
        try:
            rule = PolicyRule.model_validate(entry)
        except ValidationError as exc:
            raise PolicyParseError(f"{path}: policies[{i}] invalid — {exc.errors()}") from exc
        if rule.name in seen:
            raise PolicyParseError(f"{path}: duplicate policy name {rule.name!r}")
        seen.add(rule.name)
        rules.append(rule)
    return rules
