from __future__ import annotations

import argparse
import sys
from pathlib import Path

INIT_FILES = (
    "ruidong/__init__.py",
    "ruidong/agent/__init__.py",
    "ruidong/agent/v1/__init__.py",
)


def generate(*, repo_root: Path, out_dir: Path) -> None:
    try:
        import grpc_tools
        from grpc_tools import protoc
    except ImportError as exc:  # pragma: no cover - exercised by CLI environments
        raise SystemExit(
            "grpcio-tools is required to generate Python protobuf bindings. "
            "Run `uv sync --group dev` first."
        ) from exc

    proto_root = repo_root / "proto"
    proto_files = sorted(str(path) for path in proto_root.rglob("*.proto"))
    if not proto_files:
        raise SystemExit(f"no proto files found under {proto_root}")
    out_dir.mkdir(parents=True, exist_ok=True)
    include_path = Path(grpc_tools.__file__).resolve().parent / "_proto"
    args = [
        "grpc_tools.protoc",
        f"-I{proto_root}",
        f"-I{include_path}",
        f"--python_out={out_dir}",
        *proto_files,
    ]
    result = protoc.main(args)
    if result != 0:
        raise SystemExit(result)
    for init_file in INIT_FILES:
        path = out_dir / init_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("packages/rd-agent-proto/src"),
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir
    generate(repo_root=repo_root, out_dir=out_dir.resolve())
    print(f"Generated Python protobuf bindings into {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

