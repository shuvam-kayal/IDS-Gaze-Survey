# Acceptance criteria and traceability

Cross-workstream technical decisions and the exact A-AF traceability table are
maintained in
[`architecture/INTEGRATION_FREEZE.md`](../architecture/INTEGRATION_FREEZE.md).

- Camera capture requires informed consent; withdrawal stops capture.
- Camera denial/unavailability/interruption never blocks surveys and non-gaze analysis.
- Missing gaze is reason-coded, never silently zero-filled.
- Events/results retain schema/config/feature/model provenance.
- Assignment, survey consolidation and AOI mapping are deterministic for pinned versions.
- Retries preserve event IDs; ingestion is idempotent.
- ML results report modality, sample size, split strategy, metrics, model version and limitations.
- Fixtures contain no secrets or identifiable data.

Traceability: A–C/J–K/M -> researcher console/control plane; D–I/L/N/O -> participant SDK/demo; P–X -> telemetry/gaze/feature services; Y–AE -> analytics/results; AF -> all subsystems. Replace the freeze table's planned/local statuses with VERIFIED only when the stated evidence and linked test/PR exist.
