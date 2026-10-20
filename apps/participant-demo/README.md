# Participant demo

This dependency-free browser demo connects the participant SDK invitation, separate research/camera consent, optional camera request, P3 adapter boundary, timed trial, AOI geometry, privacy-filtered interactions, and versioned sample survey.

## Run it

From this directory, run `python3 server.py` (or `npm run dev` if npm is available), then open `http://localhost:5173/?experience_id=<published-experience-id>`. The default is live P2 mode: after the participant accepts the invitation, the demo POSTs to `/v1/sessions/bootstrap`, then fetches the server-pinned StudyConfig, AOIConfig, QuestionConfig, SurveyPlan and SurveyPlan details. Start the repository API with `docker compose up --build` in the repository root. The browser sends interaction events to the existing `http://localhost:8000/v1/events` route; it does not send gaze samples in this slice.

For an explicitly offline fixture-only run, use `http://localhost:5173/?mode=offline`. Offline mode is never selected automatically and does not create a live P2 session. The live loader fails visibly if the Experience ID is missing, the origin is unauthorized, a resource is unavailable, or a pinned resource does not validate; it does not fall back to `demo-config.json`.

The researcher control plane exposes the contract v1 session-bootstrap and pinned Study/AOI/Question config resources under `/v1/sessions`. Consent records and survey answers stay in page memory, and survey persistence is not claimed. The event queue is bounded in memory and retains events through temporary network failures while this page remains open. It drops pending research events on withdrawal and does not flush them as part of withdrawal.

Camera access is requested only after both separate consent choices. The demo accepts a P3 `ProviderAdapter` through `window.IDS_GAZE_PROVIDER`; it does not bundle WebGazer or implement gaze processing. Without that adapter, the camera flow reports a provider fallback and the non-gaze journey continues. To supply the adapter, load its browser bundle before `main.js`. The SDK passes explicit consent, session, geometry, and callbacks; the provider owns camera acquisition and cleanup through its supported API.

The live trial timing is derived from the selected study's pinned survey-plan details; the offline fixture uses its checked-in timing rule. The survey is rendered from the server-pinned `QuestionConfig` and `SurveyPlan` in live mode. Interaction capture excludes form and editable fields and uses only the fixture's explicit event allow-list. The current P2 bootstrap exposes consent policy versions, not policy text; the demo displays neutral local explanatory text while preserving those server versions, so a production participant surface still needs its approved consent-content integration.
