from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateStep:
    name: str
    command: tuple[str, ...]


def default_steps(*, coverage: bool = True) -> tuple[GateStep, ...]:
    test_step = (
        GateStep(
            "coverage-tests",
            ("uv", "run", "coverage", "run", "-m", "pytest", "-q"),
        ),
        GateStep("coverage-report", ("uv", "run", "coverage", "report")),
    ) if coverage else (
        GateStep("tests", ("uv", "run", "pytest", "-q")),
    )
    return (
        GateStep("lint", ("uv", "run", "ruff", "check", ".")),
        *test_step,
        GateStep(
            "golden-traces",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "packages/rd-replay-evals/tests/test_golden_traces_self_consistent.py",
            ),
        ),
        GateStep(
            "typing-markers",
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "tools/tests/test_package_typing_markers.py",
            ),
        ),
        GateStep(
            "protocol-contracts",
            ("uv", "run", "python", "tools/scripts/verify_protocol.py"),
        ),
        GateStep(
            "governance-docs",
            ("uv", "run", "python", "tools/scripts/verify_governance.py"),
        ),
        GateStep(
            "reference-host-examples",
            ("uv", "run", "pytest", "-q", "examples/reference_host/tests"),
        ),
        GateStep(
            "syntax-compile",
            ("uv", "run", "python", "-m", "compileall", "-q", "packages", "tools", "examples"),
        ),
    )


def wheel_smoke_steps(packages: tuple[str, ...], *, dist_dir: Path) -> tuple[GateStep, ...]:
    return tuple(
        GateStep(
            f"wheel-smoke:{package}",
            (
                "uv",
                "run",
                "--no-sync",
                "python",
                "tools/scripts/verify_wheel_install.py",
                package,
                "--dist-dir",
                str(dist_dir),
            ),
        )
        for package in packages
    )


def run_steps(steps: tuple[GateStep, ...], *, repo_root: Path) -> None:
    for step in steps:
        print(f"==> {step.name}: {' '.join(step.command)}", flush=True)
        subprocess.run(step.command, cwd=repo_root, check=True)


def build_steps(
    *,
    coverage: bool,
    wheel_smoke_packages: tuple[str, ...],
    dist_dir: Path,
) -> tuple[GateStep, ...]:
    return (
        *default_steps(coverage=coverage),
        *wheel_smoke_steps(wheel_smoke_packages, dist_dir=dist_dir),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--no-coverage",
        action="store_true",
        help="Run pytest without coverage. Intended only for local debugging.",
    )
    parser.add_argument(
        "--wheel-smoke-package",
        action="append",
        default=[],
        help="Run wheel install smoke for a built package. May be passed more than once.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path("dist"),
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    dist_dir = args.dist_dir
    if not dist_dir.is_absolute():
        dist_dir = repo_root / dist_dir
    steps = build_steps(
        coverage=not args.no_coverage,
        wheel_smoke_packages=tuple(args.wheel_smoke_package),
        dist_dir=dist_dir.resolve(),
    )
    run_steps(steps, repo_root=repo_root)
    print("Release gate passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
