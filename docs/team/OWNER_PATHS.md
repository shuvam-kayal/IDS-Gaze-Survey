# Exact folder ownership

| Owner | Owns | Does not own |
|---|---|---|
| P1 | packages/participant-sdk/**; apps/participant-demo/** (create); browser tests for consent/camera/events/AOI geometry | external gaze adapter, fixation/feature calculations, ML interpretation |
| P2 | apps/researcher-console/src/features/experiences/**, studies/**, aois/**, questions/**, users/**; services/control_plane/** | telemetry persistence, gaze estimation, ML algorithms |
| P3 | services/telemetry/**, services/gaze_engine/**, services/feature_engine/**; canonical gaze and feature fixtures | camera permission UI, researcher app shell, model interpretation |
| P4 | services/analytics/**; apps/researcher-console/src/features/analytics/**; ML/evaluation fixtures | gaze-provider normalization, raw measurement definitions, study config screens |

Shared protected-by-convention paths: contracts/**, tests/test_contracts.py, tests/test_api.py, services/api/app.py, package.json, pyproject.toml, tsconfig.base.json, docker-compose.yml, infra/**, .github/workflows/**, database/** and docs/features/MASTER_FEATURE_CHECKLIST.md. Shared changes require an affected-owner review. CODEOWNERS remains unassigned until contributor GitHub handles are confirmed.

The owner paths define responsibility, not permission to change shared schemas unilaterally. Every cross-boundary contract change requires producer and consumer review.
