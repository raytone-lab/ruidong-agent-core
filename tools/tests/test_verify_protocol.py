from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "scripts" / "verify_protocol.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_protocol", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_protocol_verification_passes() -> None:
    module = _load_module()

    module.verify(REPO_ROOT)

