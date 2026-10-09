# Webcam-Assisted Digital Survey and Attention Analytics Platform

A research platform intended to combine survey responses, browser interaction telemetry and optional webcam-derived gaze signals to study user attention. This repository currently contains the **contract-first starter scaffold**, not a finished or production-ready product.

## Start locally

- Copy `.env.example` to `.env`.
- Run `docker compose up --build`.
- Check `http://localhost:8000/health` and `http://localhost:8000/docs`.
- For checks, see [Local development](docs/setup/LOCAL_DEVELOPMENT.md).

## Team ownership

The frozen four-person split is documented in [Work division](docs/team/WORK_DIVISION.md), with the [ownership matrix](docs/team/OWNERSHIP_MATRIX.md), [parallel development guide](docs/team/PARALLEL_DEVELOPMENT_GUIDE.md) and [integration plan](docs/team/INTEGRATION_PLAN.md). P1 owns participant/browser runtime; P2 owns researcher/control plane; P3 owns telemetry/gaze/feature engineering; P4 owns statistical/ML analytics and results.

## Contracts and features

Versioned JSON Schemas and synthetic examples live in `contracts/`. Read [contract versioning](docs/contracts/CONTRACT_VERSIONING.md) and the [A–AF master feature checklist](docs/features/MASTER_FEATURE_CHECKLIST.md). Camera denial, unavailability or interruption must not block survey and non-gaze analysis; see [gaze and fallback](docs/architecture/GAZE_AND_FALLBACK.md).

## Current limitations

The minimal API has a health route and a shape-validating event endpoint. **Events are not persisted.** Authentication, database migrations, real session/config APIs, camera capture, gaze-provider integration, feature computation, models and dashboards are not implemented yet. TypeScript packages are domain/interface scaffolds rather than full web applications. Do not use this repository to collect real participant data.

## Safety and research quality

Review [privacy and consent](docs/security/PRIVACY_AND_CONSENT.md) before implementation involving participants. Fixtures must be synthetic or appropriately consented/de-identified. Model evaluation must report modality, missingness, sample size, validation strategy and limitations.
