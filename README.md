# Webcam-Assisted Digital Survey and Attention Analytics Platform

A research platform intended to combine survey responses, browser interaction telemetry and optional webcam-derived gaze signals to study user attention. This repository currently contains the **contract-first starter scaffold**, not a finished or production-ready product.

## First-time setup

Windows PowerShell (the supported one-command path):

```powershell
.\scripts\setup.ps1
```

This checks Docker Desktop, Python 3.11+, Node/npm and repository files; creates
`.venv`; installs the declared Python and npm dependencies; starts the existing
PostgreSQL 16 Compose service; waits for its healthcheck; migrates the
development database; creates the separate `attention_test` database if needed;
and migrates that database independently. It never drops or resets either
database. Local connection settings are written to ignored `.env.test` without
printing passwords.

Linux/macOS can run the same steps with PowerShell 7 (`pwsh
./scripts/setup.ps1`), or follow [Local development](docs/setup/LOCAL_DEVELOPMENT.md).

## Daily development

Start the API and PostgreSQL with:

```powershell
.\scripts\start.ps1
```

Then check `http://localhost:8000/health` and `http://localhost:8000/docs`.
Run ordinary unit tests with `.\.venv\Scripts\python.exe -m pytest -q` and the
PostgreSQL integration tests with:

```powershell
.\scripts\test-postgres.ps1
```

Stop services without deleting database data with `docker compose down`.
Never use `docker compose down -v` as part of routine setup or shutdown.

## Team ownership

The frozen four-person split is documented in [Work division](docs/team/WORK_DIVISION.md), with the [ownership matrix](docs/team/OWNERSHIP_MATRIX.md), [parallel development guide](docs/team/PARALLEL_DEVELOPMENT_GUIDE.md) and [integration plan](docs/team/INTEGRATION_PLAN.md). P1 owns participant/browser runtime; P2 owns researcher/control plane; P3 owns telemetry/gaze/feature engineering; P4 owns statistical/ML analytics and results.

## Contracts and features

Versioned JSON Schemas and synthetic examples live in `contracts/`. Read [contract versioning](docs/contracts/CONTRACT_VERSIONING.md) and the [A–AF master feature checklist](docs/features/MASTER_FEATURE_CHECKLIST.md). Camera denial, unavailability or interruption must not block survey and non-gaze analysis; see [gaze and fallback](docs/architecture/GAZE_AND_FALLBACK.md).

The cross-workstream integration decisions are frozen in [the integration freeze](docs/architecture/INTEGRATION_FREEZE.md). It is the authority for canonical IDs, event identity and ordering, PostgreSQL/Alembic persistence, API response semantics, retention/deletion defaults, FeatureRecord missingness, the browser-to-gaze boundary, AOI geometry, metric definitions, ownership, and implementation order.

## Current limitations

The minimal API has a health route and a shape-validating event endpoint. **Events are not persisted.** Authentication, database migrations, real session/config APIs, camera capture, gaze-provider integration, feature computation, models and dashboards are not implemented yet. TypeScript packages are domain/interface scaffolds rather than full web applications. Do not use this repository to collect real participant data.

## Safety and research quality

Review [privacy and consent](docs/security/PRIVACY_AND_CONSENT.md) before implementation involving participants. Fixtures must be synthetic or appropriately consented/de-identified. Model evaluation must report modality, missingness, sample size, validation strategy and limitations.
