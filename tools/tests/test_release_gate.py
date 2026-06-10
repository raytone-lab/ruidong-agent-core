from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "scripts" / "release_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("release_gate", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_release_gate_steps_include_coverage_and_examples() -> None:
    module = _load_module()

    steps = module.default_steps()

    assert [step.name for step in steps] == [
        "lint",
        "coverage-tests",
        "coverage-report",
        "golden-traces",
        "typing-markers",
        "reference-host-examples",
        "syntax-compile",
    ]


def test_release_gate_can_disable_coverage_for_local_debugging() -> None:
    module = _load_module()

    steps = module.default_steps(coverage=False)

    assert [step.name for step in steps[:2]] == ["lint", "tests"]
    assert "coverage" not in " ".join(steps[1].command)


def test_release_gate_builds_wheel_smoke_steps() -> None:
    module = _load_module()

    steps = module.wheel_smoke_steps(
        ("rd-agent-core", "rd-agent-contracts"),
        dist_dir=REPO_ROOT / "dist",
    )

    assert [step.name for step in steps] == [
        "wheel-smoke:rd-agent-core",
        "wheel-smoke:rd-agent-contracts",
    ]
    assert steps[0].command[-3:] == (
        "rd-agent-core",
        "--dist-dir",
        str(REPO_ROOT / "dist"),
    )


def test_release_gate_run_steps_uses_repo_root(monkeypatch) -> None:
    module = _load_module()
    calls = []

    def _run(command, *, cwd, check):
        calls.append((tuple(command), cwd, check))

    monkeypatch.setattr(module.subprocess, "run", _run)
    module.run_steps(
        (module.GateStep("sample", ("python", "--version")),),
        repo_root=REPO_ROOT,
    )

    assert calls == [((("python", "--version")), REPO_ROOT, True)]
