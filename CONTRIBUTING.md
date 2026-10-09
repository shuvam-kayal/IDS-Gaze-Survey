# Contributing

Read team ownership, architecture and contract versioning docs before taking a task. Work inside owner paths. Cross-boundary changes require affected-owner review. Shared contracts require rationale, before/after examples, compatibility notes and tests. Update feature traceability when implementation changes. Use synthetic fixtures only; never commit secrets or identifiable participant data. Keep PRs small and coordinate root manifests, CI, Compose and migrations with the integrator.

Checks: `pip install -e ".[dev]"`, `ruff check .`, `pytest`, `npm install`, `npm run typecheck`; local services: `docker compose up --build`.
