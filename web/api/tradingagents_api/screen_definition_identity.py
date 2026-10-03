"""Versioned, additive screen identity; original capture/history keys stay intact.

This metadata does not grant access or authorize merging histories. Discovery
must prove ownership and retain raw definitions and criterion slot ordering.
"""

import hashlib
import json
from copy import deepcopy


def semantic_definition(definition):
    if not isinstance(definition, dict) or not isinstance(definition.get("filters"), list):
        raise ValueError("Invalid screen definition")
    result = deepcopy(definition)
    for criterion in result["filters"]:
        if not isinstance(criterion, dict):
            raise ValueError("Invalid criterion definition")
        # Only these presentation/no-bound fields are semantically inert.
        criterion.pop("_label", None)
        for bound in ("min", "max"):
            if criterion.get(bound) is None:
                criterion.pop(bound, None)
    # Reject non-JSON/nonfinite definitions rather than deriving an unstable ID.
    json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return result


def definition_identity(definition):
    canonical = semantic_definition(definition)
    envelope = {"schema_version": 1, "screen": canonical}
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    return {"schema_version": 1, "sha256": hashlib.sha256(encoded).hexdigest()}


def validate_definition_identity(snapshot):
    """Optional additive metadata: legacy absence is valid; supplied mismatch is not."""
    if "definition_identity" not in snapshot:
        return
    supplied = snapshot["definition_identity"]
    if (
        not isinstance(supplied, dict)
        or type(supplied.get("schema_version")) is not int
        or supplied != definition_identity(snapshot.get("definition"))
    ):
        raise ValueError("Captured semantic definition identity is invalid or inconsistent")


def _typed_equal(a, b):
    """Keep booleans, integers and floats distinct as versioned JSON identity does."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_typed_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_typed_equal(x, y) for x, y in zip(a, b, strict=False))
    return a == b


def criteria_equivalent(a, b):
    """Compare corresponding slots; never renumber, coalesce or modify evidence."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False

    def meaningful(c):
        return {
            k: v for k, v in c.items() if k != "_label" and not (k in ("min", "max") and v is None)
        }

    return _typed_equal(meaningful(a), meaningful(b))
