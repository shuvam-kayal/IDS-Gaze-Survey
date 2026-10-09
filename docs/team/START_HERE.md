# Start here — team setup

1. Read docs/team/WORK_DIVISION.md, OWNER_PATHS.md, OWNERSHIP_MATRIX.md and BRANCH_AND_PR_WORKFLOW.md.
2. Read docs/contracts/CONTRACT_VERSIONING.md and inspect contracts/schemas plus contracts/examples.
3. Clone master and create your own branch; do not work on a shared feature branch.
4. Run Python tests and TypeScript typecheck before editing.
5. Begin with your synthetic-fixture milestone in docs/team/INTEGRATION_PLAN.md.
6. Keep every A–AF checklist row marked planned until implementation and tests prove it. A starter interface is not a completed feature.

P1: emit valid EventEnvelope events and test denied-camera flow. P2: produce versioned Experience/Study/AOI/question configs. P3: turn synthetic events into non-gaze FeatureRecords and keep gaze adapter provider-neutral. P4: consume FeatureRecords and emit AnalysisResult with sample size/modality/limitations.
