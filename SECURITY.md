# Security Policy

## Supported Versions

Security fixes are handled on the current release candidate line documented in
`docs/releases/README.md`:

- `rd-agent-contracts`
- `rd-llm-adapter`
- `rd-agent-core`

`rd-llm-gateway`, `rd-replay-evals`, and `rd-tools` are maintained because they
remain in the workspace and release workflow, but new host integrations should
not build product-critical security assumptions on `rd-llm-gateway`.

## Reporting

Report vulnerabilities privately through GitHub private security advisories or
directly to the repository owner. Do not open a public issue for secrets,
credential handling, tenant isolation, workspace access, or remote execution
findings until a maintainer confirms disclosure is safe.

## Security Boundary

This SDK is host-neutral. It provides contracts, runtime control flow, safety
hooks, and conformance tests, but the host remains responsible for:

- user, tenant, and project authorization;
- workspace lease, file-system, and network access control;
- tool registry filtering and dangerous action confirmation;
- provider credentials, model routing, retry, timeout, and rate limiting;
- PII redaction, audit retention, billing, and artifact storage lifecycle.

Security-sensitive host implementations should run the conformance suite in
their own CI and add product-specific integration tests around permissions,
workspace isolation, and tool execution.

