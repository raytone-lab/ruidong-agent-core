# Repository Governance

## Ownership

Repository ownership is encoded in `CODEOWNERS`. Until package-specific teams
are assigned, the default owner is `@shinelee211-arch`.

Any change under these paths requires owner review:

- `packages/`
- `proto/`
- `docs/`
- `examples/`
- `tools/`
- `.github/`
- root governance files

## Branch and Release Policy

- Normal development branches should use the `codex/` or `feature/` prefix.
- Release tags must follow `rd-<package-name>-v<version>`.
- `tools/scripts/verify_release_tag.py` checks that the tag package and version
  match the target package `pyproject.toml`.
- `docs/releases/` stores versioned release notes and the release-doc entry.

## Required Gates

Local development gate:

```bash
uv run python tools/scripts/release_gate.py --no-coverage
```

Release gate:

```bash
uv run python tools/scripts/release_gate.py
```

The release gate runs:

- `lint`
- `coverage-tests` or `tests`
- `coverage-report` when coverage is enabled
- `golden-traces`
- `typing-markers`
- `protocol-contracts`
- `governance-docs`
- `reference-host-examples`
- `syntax-compile`

## Documentation Rules

- Public product or architecture claims must cite code evidence or a verifying
  command.
- New public APIs must update `docs/API-REFERENCE.md`.
- Compatibility changes must update `docs/API-STABILITY.md` and release notes.
- New event types must update `docs/EVENT-PAYLOAD-SCHEMA.md`,
  `docs/PROTOCOL-CONTRACT.md`, and `proto/ruidong/agent/v1/events.proto`.
- New host responsibilities must update `docs/HOST-INTEGRATION-CONTRACT.md`.
- Proto changes must regenerate `rd-agent-proto` bindings and pass
  `tools/scripts/verify_protocol.py`.

## Dependency Policy

- `rd-agent-contracts` should remain dependency-free unless a dependency is a
  deliberate public contract decision.
- `rd-agent-core` must not depend on web frameworks, ORMs, Redis, S3, SaaS app
  modules, or UI packages.
- Provider SDK dependencies should remain optional where possible.
- The root `uv.lock` should be tracked for reproducible development and CI.

## Verification Ownership

The governance verifier is `tools/scripts/verify_governance.py`. It checks that
required governance files, product docs, protocol docs, proto files, code-owned
paths, package versions, event names, and markdown links remain coherent.

If a verifier assertion fails, prefer updating the source code, docs, proto, or
test coverage that represents the actual intended behavior instead of weakening
the verifier.
