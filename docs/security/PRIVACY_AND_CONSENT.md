# Privacy and consent baseline

This is engineering guidance, not legal advice or a substitute for ethics
review. Cross-workstream technical lifecycle decisions are frozen in
[`architecture/INTEGRATION_FREEZE.md`](../architecture/INTEGRATION_FREEZE.md).

Explain purpose, data types, duration, processing, retention, sharing, risks
and withdrawal before collection. Research consent and camera permission are
separate. Camera is opt-in with visible status/stop control; stop on withdrawal
or session end. Prefer transient/on-device frame handling and do not persist
raw video/images by default. Minimize identifiers; use pseudonymous IDs, role
restrictions, TLS in deployment and audit sensitive actions. The freeze defines
conservative operational retention defaults, deletion propagation, and
verification behavior; legal, institutional, and ethics review is still
required before real participant collection. Never log raw answers, frames,
tokens or sensitive payloads by default. Fixtures must be synthetic or
appropriately consented/de-identified. Before deployment add threat model,
dependency scan, origin allowlist, rate limits, encryption, restore test and
incident process.
