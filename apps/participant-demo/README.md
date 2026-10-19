# Participant demo

This dependency-free browser demo connects the participant SDK invitation, separate research/camera consent, optional camera request, P3 adapter boundary, timed trial, AOI geometry, privacy-filtered interactions, and versioned sample survey.

## Run it

From this directory, run `python3 server.py` (or `npm run dev` if npm is available), then open [http://localhost:5173](http://localhost:5173). For event delivery, start the repository API with `docker compose up --build` in the repository root. The browser sends events to `http://localhost:8000/v1/events`; the checked-in compose configuration already allows the demo origin on port 5173.

The researcher control plane exposes the contract v1 session-bootstrap and pinned Study/AOI/Question config resources under `/v1/sessions`. `demo-config.json` remains a static sample unless the participant demo is configured to call those endpoints; consent records and survey answers stay in page memory, and event submission still follows the separate API flow. The event queue is bounded in memory and retains events through temporary network failures while this page remains open. It drops pending research events on withdrawal and does not flush them as part of withdrawal.

Camera access is requested only after both separate consent choices. The demo accepts a P3 `ProviderAdapter` through `window.IDS_GAZE_PROVIDER`; it does not bundle WebGazer or implement gaze processing. Without that adapter, the camera flow reports a provider fallback and the non-gaze journey continues. To supply the adapter, load its browser bundle before `main.js`. The provider receives the SDK's revocable `camera_source` capability rather than a raw `MediaStream`.

The trial has a 15-second sample timing rule. The survey is rendered from the fixture's pinned `QuestionConfig` and `SurveyPlan`. Interaction capture excludes form and editable fields and uses only the fixture's explicit event allow-list.
