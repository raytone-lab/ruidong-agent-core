from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "scripts" / "verify_governance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_governance", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_event_value_to_proto_enum() -> None:
    module = _load_module()

    assert module._event_value_to_proto_enum("turn_started") == "EVENT_TYPE_TURN_STARTED"
    assert module._event_value_to_proto_enum("loop_break:repeat") == (
        "EVENT_TYPE_LOOP_BREAK_REPEAT"
    )


def test_repository_governance_verification_passes() -> None:
    module = _load_module()

    module.verify(REPO_ROOT)

