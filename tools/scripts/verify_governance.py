from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REQUIRED_ROOT_FILES = (
    ".editorconfig",
    "AGENTS.md",
    "CODEOWNERS",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "uv.lock",
)

REQUIRED_DOC_FILES = (
    "docs/README.md",
    "docs/PRODUCT-DESIGN.md",
    "docs/ARCHITECTURE.md",
    "docs/GLOSSARY.md",
    "docs/MULTILANGUAGE-CONSUMPTION.md",
    "docs/PROTOCOL-CONTRACT.md",
    "docs/PROTO-RELEASE.md",
    "docs/REPOSITORY-GOVERNANCE.md",
    "docs/API-REFERENCE.md",
    "docs/API-STABILITY.md",
    "docs/EVENT-PAYLOAD-SCHEMA.md",
    "docs/HOST-INTEGRATION-CONTRACT.md",
    "docs/QUICKSTART.md",
    "docs/SDK-OVERVIEW.md",
    "docs/adr/0001-protocol-source-of-truth.md",
)

REQUIRED_PROTO_FILES = (
    "proto/README.md",
    "proto/ruidong/agent/v1/events.proto",
    "proto/ruidong/agent/v1/transcript.proto",
    "proto/ruidong/agent/v1/runtime.proto",
    "buf.yaml",
    "buf.gen.yaml",
)

CODEOWNER_PATHS = (
    "/packages/rd-agent-contracts/",
    "/packages/rd-agent-proto/",
    "/packages/rd-agent-core/",
    "/packages/rd-llm-adapter/",
    "/packages/rd-llm-gateway/",
    "/packages/rd-replay-evals/",
    "/tools/",
    "/docs/",
    "/proto/",
    "/examples/",
    "/.github/",
)

DOC_INDEX_REQUIRED = (
    "PRODUCT-DESIGN.md",
    "ARCHITECTURE.md",
    "PROTOCOL-CONTRACT.md",
    "PROTO-RELEASE.md",
    "MULTILANGUAGE-CONSUMPTION.md",
    "REPOSITORY-GOVERNANCE.md",
    "GLOSSARY.md",
    "API-REFERENCE.md",
    "API-STABILITY.md",
    "EVENT-PAYLOAD-SCHEMA.md",
    "HOST-INTEGRATION-CONTRACT.md",
    "QUICKSTART.md",
    "SDK-OVERVIEW.md",
)

STANDARD_ADAPTER_EVENTS = (
    "TextDelta",
    "ReasoningDelta",
    "ToolCallStart",
    "ToolCallIdDelta",
    "ToolCallNameDelta",
    "ToolCallArgsDelta",
    "ToolCallEnd",
    "UsageUpdate",
    "TurnDone",
)

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SKIP_MARKDOWN_DIRS = {
    ".git",
    ".mypy_cache",
    ".npm-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


@dataclass(frozen=True)
class WorkspacePackage:
    name: str
    version: str
    package_dir: Path


class GovernanceError(AssertionError):
    """Raised when repository governance checks fail."""


def verify(repo_root: Path) -> None:
    repo_root = repo_root.resolve()
    _assert_required_files(repo_root, REQUIRED_ROOT_FILES)
    _assert_required_files(repo_root, REQUIRED_DOC_FILES)
    _assert_required_files(repo_root, REQUIRED_PROTO_FILES)
    packages = _workspace_packages(repo_root)
    core_event_values = _core_event_values()

    _assert_codeowners(repo_root)
    _assert_uv_lock_policy(repo_root)
    _assert_readme_indexes(repo_root)
    _assert_versions_documented(repo_root, packages)
    _assert_protocol_docs(repo_root, core_event_values)
    _assert_proto_events(repo_root, core_event_values)
    _assert_product_and_architecture_docs(repo_root, packages)
    _assert_release_gate_docs(repo_root)
    _assert_markdown_links(repo_root)


def _assert_required_files(repo_root: Path, paths: Iterable[str]) -> None:
    missing = [path for path in paths if not (repo_root / path).is_file()]
    if missing:
        raise GovernanceError(f"missing required files: {', '.join(missing)}")


def _workspace_packages(repo_root: Path) -> dict[str, WorkspacePackage]:
    package_paths = sorted((repo_root / "packages").glob("rd-*/pyproject.toml"))
    package_paths.append(repo_root / "tools" / "pyproject.toml")
    packages: dict[str, WorkspacePackage] = {}
    for pyproject in package_paths:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        name = str(project["name"])
        packages[name] = WorkspacePackage(
            name=name,
            version=str(project["version"]),
            package_dir=pyproject.parent,
        )
    return packages


def _core_event_values() -> tuple[str, ...]:
    from rd_agent_core import CoreEventType

    return tuple(event.value for event in CoreEventType)


def _assert_codeowners(repo_root: Path) -> None:
    content = (repo_root / "CODEOWNERS").read_text(encoding="utf-8")
    missing = [path for path in CODEOWNER_PATHS if path not in content]
    if missing:
        raise GovernanceError(f"CODEOWNERS missing path coverage: {', '.join(missing)}")


def _assert_uv_lock_policy(repo_root: Path) -> None:
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    ignored = [line for line in gitignore if line.strip() == "uv.lock"]
    if ignored:
        raise GovernanceError("uv.lock must not be ignored; governance requires tracking it")


def _assert_readme_indexes(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    docs_index = (repo_root / "docs" / "README.md").read_text(encoding="utf-8")
    for required in DOC_INDEX_REQUIRED:
        if required not in readme:
            raise GovernanceError(f"README.md does not mention {required}")
        if required not in docs_index:
            raise GovernanceError(f"docs/README.md does not mention {required}")


def _assert_versions_documented(
    repo_root: Path,
    packages: dict[str, WorkspacePackage],
) -> None:
    docs_to_check = (
        repo_root / "README.md",
        repo_root / "docs" / "API-REFERENCE.md",
        repo_root / "docs" / "API-STABILITY.md",
        repo_root / "docs" / "QUICKSTART.md",
        repo_root / "docs" / "releases" / "README.md",
    )
    release_packages = (
        "rd-agent-contracts",
        "rd-agent-proto",
        "rd-llm-adapter",
        "rd-agent-core",
    )
    for package_name in release_packages:
        version = packages[package_name].version
        for path in docs_to_check:
            content = path.read_text(encoding="utf-8")
            if package_name not in content or version not in content:
                raise GovernanceError(
                    f"{path.relative_to(repo_root)} missing {package_name} {version}"
                )


def _assert_protocol_docs(repo_root: Path, event_values: tuple[str, ...]) -> None:
    doc = (repo_root / "docs" / "PROTOCOL-CONTRACT.md").read_text(encoding="utf-8")
    schema_version = _schema_version()
    if schema_version not in doc:
        raise GovernanceError("PROTOCOL-CONTRACT.md missing SCHEMA_VERSION")
    for event_value in event_values:
        if f"`{event_value}`" not in doc:
            raise GovernanceError(f"PROTOCOL-CONTRACT.md missing event {event_value}")
    for event_class in STANDARD_ADAPTER_EVENTS:
        if f"`{event_class}`" not in doc:
            raise GovernanceError(
                f"PROTOCOL-CONTRACT.md missing standard adapter event {event_class}"
            )


def _schema_version() -> str:
    from rd_agent_contracts import SCHEMA_VERSION

    return str(SCHEMA_VERSION)


def _assert_proto_events(repo_root: Path, event_values: tuple[str, ...]) -> None:
    proto = (repo_root / "proto" / "ruidong" / "agent" / "v1" / "events.proto")
    content = proto.read_text(encoding="utf-8")
    for event_value in event_values:
        enum_name = _event_value_to_proto_enum(event_value)
        if enum_name not in content:
            raise GovernanceError(f"events.proto missing enum {enum_name}")


def _event_value_to_proto_enum(event_value: str) -> str:
    return "EVENT_TYPE_" + event_value.upper().replace(":", "_").replace("-", "_")


def _assert_product_and_architecture_docs(
    repo_root: Path,
    packages: dict[str, WorkspacePackage],
) -> None:
    product = (repo_root / "docs" / "PRODUCT-DESIGN.md").read_text(encoding="utf-8")
    architecture = (repo_root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for section in ("Product Thesis", "Users", "Product Surfaces", "Non-Goals"):
        if f"## {section}" not in product:
            raise GovernanceError(f"PRODUCT-DESIGN.md missing section {section}")
    for package_name in packages:
        if package_name not in architecture and package_name != "rd-tools":
            raise GovernanceError(f"ARCHITECTURE.md missing package {package_name}")
    evidence_paths = (
        "packages/rd-agent-core/src/rd_agent_core/run.py",
        "packages/rd-agent-core/src/rd_agent_core/turn.py",
        "packages/rd-agent-contracts/src/rd_agent_contracts/events.py",
        "packages/rd-llm-adapter/src/rd_llm_adapter/events.py",
        "examples/reference_host/sqlite_reference_host.py",
    )
    for evidence_path in evidence_paths:
        if evidence_path not in product and evidence_path not in architecture:
            raise GovernanceError(f"product/architecture docs missing {evidence_path}")


def _assert_release_gate_docs(repo_root: Path) -> None:
    governance = (repo_root / "docs" / "REPOSITORY-GOVERNANCE.md").read_text(
        encoding="utf-8"
    )
    release_gate = _load_release_gate(repo_root)
    step_names = [step.name for step in release_gate.default_steps()]
    for step_name in step_names:
        if step_name not in governance:
            raise GovernanceError(f"REPOSITORY-GOVERNANCE.md missing gate {step_name}")


def _load_release_gate(repo_root: Path):
    script = repo_root / "tools" / "scripts" / "release_gate.py"
    spec = importlib.util.spec_from_file_location("release_gate_for_governance", script)
    if spec is None or spec.loader is None:
        raise GovernanceError("could not load release_gate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_markdown_links(repo_root: Path) -> None:
    failures: list[str] = []
    for path in sorted(repo_root.rglob("*.md")):
        if SKIP_MARKDOWN_DIRS & set(path.parts):
            continue
        content = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(content):
            target = raw_target.strip()
            if _is_external_or_anchor(target):
                continue
            target_path = target.split("#", maxsplit=1)[0]
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            try:
                resolved.relative_to(repo_root)
            except ValueError:
                failures.append(f"{path.relative_to(repo_root)} -> {target}")
                continue
            if not resolved.exists():
                failures.append(f"{path.relative_to(repo_root)} -> {target}")
    if failures:
        raise GovernanceError("broken markdown links:\n" + "\n".join(failures))


def _is_external_or_anchor(target: str) -> bool:
    return (
        target.startswith("#")
        or target.startswith("http://")
        or target.startswith("https://")
        or target.startswith("mailto:")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args(argv)
    verify(args.repo_root)
    print("Governance verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
