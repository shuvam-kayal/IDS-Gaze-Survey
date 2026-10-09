# Master feature checklist (A–AF)

All items start planned until implementation and acceptance tests prove otherwise.

| ID | Feature | Owner | Minimum evidence |
|---|---|---|---|
| A | Experience registry and origin validation | P2 | CRUD/origin tests |
| B | Multiple Studies per Experience | P2 | 2+ study fixture |
| C | Eligibility and multi-study assignment | P2 | overlap test |
| D | Invitation popup and decline | P1 | accessible browser test |
| E | Research consent, camera consent, withdrawal | P1/P2 | state/audit tests |
| F | Camera granted/denied/unavailable/interrupted | P1 | all-state tests |
| G | Session bootstrap and config versions | P1/P2 | contract tests |
| H | Trial lifecycle and timers | P1 | lifecycle tests |
| I | Survey runtime and validation | P1 | question fixtures |
| J | Question authoring/versioning | P2 | config tests |
| K | Survey timing/consolidation | P2 | deterministic tests |
| L | Click/hover/scroll/navigation/visibility | P1 | event fixtures |
| M | AOI authoring and versions | P2 | schema/UI tests |
| N | Dynamic AOI geometry after layout changes | P1 | scroll/resize/zoom tests |
| O | Versioned event envelope | P1/P3 | schema tests |
| P | Ingestion validation/dedup/order | P3 | idempotency tests |
| Q | Telemetry persistence and retention | P3 | integration/deletion tests |
| R | External gaze adapter boundary | P3 | provider contract tests |
| S | Canonical GazeRecord normalization | P3 | normalized fixtures |
| T | Calibration and gaze quality | P3 | quality tests |
| U | Fixations and gaze-to-AOI mapping | P3 | synthetic trace tests |
| V | TTFF, dwell, revisits, transitions, entropy, scan paths | P3 | metric tests |
| W | Non-gaze timing/interaction/survey features | P3 | camera-denied tests |
| X | Reusable universal FeatureRecords | P3 | schema/reproducibility tests |
| Y | Descriptive statistics | P4 | known-answer tests |
| Z | Correlations, group tests, effect sizes | P4 | assumption/known-answer tests |
| AA | ML baselines and experiments | P4 | leakage-safe evaluation |
| AB | Gaze and non-gaze fallback models | P4 | both-mode tests |
| AC | Evaluation, uncertainty, explainability | P4 | reproducible report |
| AD | Heatmaps and analytics visualizations | P4 | visual fixtures |
| AE | Evidence-linked reports/recommendations | P4 | provenance tests |
| AF | Privacy, roles, retention, audit, operations | All by subsystem | security/ops checklist |

Every row needs an owner, issue/PR, status and test evidence. Do not claim scientific validity without adequate sample size, leakage-safe evaluation and stated limitations.
