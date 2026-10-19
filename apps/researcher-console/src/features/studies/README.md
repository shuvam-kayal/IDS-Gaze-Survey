# Researcher study configuration

Studies are scoped to one published Experience. Drafts can be created and edited; publishing freezes their `StudyConfig` schema version, AOI config version, and Question config version. Session assignment stores those exact snapshots so later drafts or releases cannot alter an active session.

## Eligibility rules

Rules are data, never executable expressions. Predicates use `{ "field": "age", "op": "gte", "value": 18 }`; supported operators are `eq`, `ne`, `in`, `contains`, `gte`, `lte`, and `exists`. Groups use `{ "all": [...] }`, `{ "any": [...] }`, and `{ "not": {...} }`. Nesting is limited to 8, group size to 20, and `in` lists to 100 values. A missing rule matches all participants. `eligible_all` assigns every matching published Study. `prioritized` assigns the highest priority match, breaking ties by ascending opaque Study ID. Assignment is stored once per session and subsequent requests return the pinned result.

Question types are `single_choice`, `multiple_choice`, `rating`, and `scale`. Choice questions require distinct non-empty choices; rating and scale questions require integer `min < max`. AOIs require unique identifiers, names, and selectors. All published configs include schema version `1.0.0` plus immutable configuration version identities.

The authoring surface is `mountStudyAuthoring` from `apps/researcher-console/src/index.ts`. It accepts JSON for timing, eligibility, AOIs, and questions; the server validates every submitted object and remains the authorization boundary.
