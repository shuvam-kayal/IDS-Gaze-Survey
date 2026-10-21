# Researcher control plane — Stages 1–3

This package provides researcher sign-in, server-side role checks, the Experience
registry, publish/archive lifecycle, audit records, and an unauthenticated
participant-origin authorization gate. Routes are mounted under
`/v1/control` by `services/api/app.py`.

It also supports multi-study authoring and versioned `StudyConfig`, `AOIConfig`,
and `QuestionConfig` snapshots, plus deterministic, per-session assignment.

## Authentication and roles

Researcher accounts are provisioned by the operator through
`CONTROL_PLANE_USERS_JSON`; the API does not accept self-registration. Store
PBKDF2-SHA256 password hashes, never plaintext passwords. A session is an
eight-hour HMAC-signed, HttpOnly, SameSite=Strict cookie. Mutating requests
must also send the CSRF token returned by `POST /auth/session` or
`GET /auth/session` in `X-CSRF-Token`. Production cookies are Secure by
default. The API fails closed with 503 when the signing secret or account
configuration is missing.

| Role | Permissions |
| --- | --- |
| `admin` | All permissions, including user management and audit access |
| `researcher` | View/manage Experiences; view/create/edit/publish/archive studies |
| `analyst` | View Experiences/studies and export results |
| `viewer` | View Experiences/studies |

The checks run on API routes; console controls only improve the interface and
are not an authorization boundary.

## Experience safety

New Experiences receive server-generated UUID identifiers and start as
`draft`. Drafts cannot authorize participant traffic. Only drafts can be
edited or published; published records cannot be edited in place. Archive is
an explicit terminal lifecycle action. Allowed origins are canonicalized to
exact HTTP(S) origins; remote HTTP, wildcard, credentials, paths, queries, and
fragments are rejected. The public
`POST /v1/control/experiences/{experience_id}/authorize-origin` endpoint uses
only the request's browser-controlled `Origin` header and matches it against a
published Experience's server-side allowlist. A client-provided origin in a
JSON body is never consulted.

Experience create/edit/publish/archive actions write an audit record in the
same PostgreSQL transaction as the change. Each record includes actor ID and
role, action, target type/ID, UTC timestamp, and action details. Audit listing
and role-matrix access require the admin role.

## Studies, configuration versions, and assignment

Studies are owned by one published Experience. Create/list at
`/experiences/{experience_id}/studies`; edit drafts at `/studies/{study_id}`;
publish or archive at `/studies/{study_id}/publish` and `/archive`. Published
Studies cannot be edited. Publishing writes schema version `1.0.0` and opaque
version identities for the Study, AOI, and Question configs. Session assignment
stores the full immutable config snapshot and version references at
`POST /experiences/{experience_id}/assign`.

Eligibility accepts only the data DSL documented in
`apps/researcher-console/src/features/studies/README.md`; expressions and code
are rejected. `eligible_all` assigns all eligible published Studies.
`prioritized` assigns the highest-priority match, then breaks ties by ascending
Study ID. Assignment is idempotent for a session ID. The browser Origin must
match the published Experience allowlist, and deployed browser origins must
also be included in `CONTROL_PLANE_CORS_ORIGINS` for preflight requests.

`POST /v1/sessions/bootstrap` creates an opaque session after matching the
protected browser Origin against the published Experience. It returns the
contract `SessionBootstrap` v1 shape and rejects other requested versions. The
session pins each eligible Study config. Fetch the exact pinned resources via
`GET /v1/sessions/{session_id}/studies/{study_id}/study-config`, `aoi-config`,
and `question-config` with each config version. The immutable
`GET /v1/sessions/{session_id}/survey-plan` follows the shared contract;
`survey-plan-details` provides question-to-study/version provenance and timing
policy details without adding fields to that contract. Consolidation preserves
question order and merges matching IDs only when their semantics also match.

## Local configuration and migrations

Generate a signing secret with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.
Generate each password hash using the project environment and a prompt so the
password is not echoed:

```python
from getpass import getpass
from services.control_plane.auth import hash_password

print(hash_password(getpass("New researcher password: ")))
```

Set `CONTROL_PLANE_SECRET` and a JSON list in `CONTROL_PLANE_USERS_JSON` in the
local `.env` file. Each entry has `username`, opaque `user_id`, `role`,
`display_name`, and `password_hash`. The Compose file passes these settings to
the API; blank values deliberately leave sign-in disabled. Set
`CONTROL_PLANE_COOKIE_SECURE=true` behind HTTPS. Local Compose defaults it to
false for HTTP development. The researcher console origin defaults to
`http://localhost:5174` in CORS; configure `CONTROL_PLANE_CORS_ORIGINS` with
the deployed console origins.

Apply schema revisions with `alembic upgrade head` after PostgreSQL is running.
The registry and audit trail use the repository's PostgreSQL/SQLAlchemy/Alembic
stack; they do not create tables or seed accounts during API startup.

`apps/researcher-console/src/features/experiences/` and `.../studies/` contain
the API clients and accessible registry/authoring screens, mounted by the
console shell at `apps/researcher-console/src/main.ts`. Run the console with
`npm run dev --workspace @ids-gaze/researcher-console` after starting the API;
the complete setup and local two-Study seed action are documented in
`apps/researcher-console/README.md`.
