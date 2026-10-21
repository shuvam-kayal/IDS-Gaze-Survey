# Researcher console

The Vite app shell provides navigation for Experiences, Studies, and P4 analytics. Start it with `npm run dev --workspace @ids-gaze/researcher-console`; the API must be running at `http://localhost:8000`, with its CORS settings allowing `http://localhost:5174`.

After signing in, use **Create E2E seed workspace** to create and publish one local Experience and two independent Studies with example AOIs, questions, timing policies, and eligibility rules. The fixture allows the participant demo origin `http://localhost:5173`. The action makes real API changes, so it is an explicit button and may be used once per clean database; the created opaque IDs are shown in the header status.

The Analytics tab lists published studies, discovers their available feature-set versions from the API, submits versioned AnalysisRequest v1 requests, and renders AnalysisResult data and limitations. Study viewing is permission-gated by the API; CSV export requires the separate results-export permission.
