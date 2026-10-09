# Branch and PR workflow

All contributors clone master after the skeleton merge and create one personal feature branch. No shared working branch is needed.

1. Clone https://github.com/shuvam-kayal/IDS-Gaze-Survey.git and enter the repository.
2. Run: git switch master; git pull --ff-only origin master.
3. Create a personal branch, e.g. feat/p1-participant-runtime, feat/p2-research-platform, feat/p3-gaze-feature-engine, or feat/p4-analytics-ml.
4. Commit only files in the owner's paths. Open a draft PR into master; do not push directly to master.
5. Before final review, fetch master and rebase or merge it into the feature branch. Resolve conflicts with the relevant owner, especially shared contracts.
6. Contract, root manifest, Docker, CI, API route wiring and migration changes require integrator/affected-owner review.

Each person works on their own branch created from the latest master. PRs should be small and must include tests, contract/example updates where needed, and the relevant A–AF checklist status.
