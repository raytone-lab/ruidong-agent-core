# Contributing

This repository is the Agent Runtime SDK and protocol workspace. Contributions
must preserve the host-neutral boundary: runtime packages cannot import SaaS
models, web frameworks, databases, queues, object stores, or UI code.

## Development Setup

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
```

The root `uv.lock` is intended to be tracked so CI and local development resolve
the same dependency graph. Package compatibility is still governed by each
package's `pyproject.toml` dependency ranges.

## Required Gates

Before opening or merging a change, run:

```bash
uv run python tools/scripts/release_gate.py --no-coverage
```

Before a release, run the full gate with coverage:

```bash
uv run python tools/scripts/release_gate.py
```

The gate covers lint, tests, governance and protocol documentation checks,
golden trace self-consistency, typing markers, reference host examples, and
syntax compilation.

## Change Rules

- Keep `rd-agent-contracts` free of runtime dependencies unless the dependency
  is part of a deliberate public contract decision.
- Keep `rd-agent-core` dependent only on `rd-agent-contracts`,
  `rd-llm-adapter`, and the Python standard library.
- Do not add product-specific behavior to `rd-agent-core`; use host adapters or
  `BusinessAgentAdapter` instead.
- Any public API or contract change must update `docs/API-REFERENCE.md`,
  `docs/API-STABILITY.md`, release notes, and protocol documentation when
  applicable.
- Any new event type must be added to `CoreEventType`, documented in
  `docs/EVENT-PAYLOAD-SCHEMA.md`, represented in `proto/ruidong/agent/v1/`,
  and covered by tests.
- New examples must be executable or explicitly marked as non-executable
  design material.

## Review Checklist

- Architecture boundary tests still prove no host framework imports leaked into
  core.
- Public API snapshot changes are intentional.
- Contract and protocol docs can be verified from code by
  `tools/scripts/verify_governance.py`.
- Release notes and versioned docs match the package versions being released.

