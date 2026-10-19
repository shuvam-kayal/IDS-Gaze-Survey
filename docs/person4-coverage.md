# Person 4 requirement coverage

Audited against Person 4 P4.1–P4.10 and architecture checklist categories Y–AE. This matrix describes P4-owned implementation only. Frozen shared schemas and P1/P2/P3 code are not modified. Cross-person production wiring remains pending review as recorded in `docs/proposals/P4_ANALYTICS_INTEGRATION.md`.

| Requirement | Verification status | Implementation and evidence |
|---|---|
| P4.1 AnalysisRequest / AnalysisResult | **P4 adapter implemented; integration pending** | Validates frozen v1 top-level fields and emits the exact frozen v1 result shape. Optional P4-only analysis types use a versioned extension inside the existing `parameters` object. Idempotency is stored in SQLAlchemy/PostgreSQL repository; shared auth, migration and job orchestration remain integrator dependencies. |
| P4.2 Readiness and data quality | **Implemented; verified** | Feature version checks; missingness, type/unit consistency, category balance, sparse cells, constants, IQR outlier candidates and sample warnings. Time/group/ID inclusion filters report included/excluded counts. No-data, insufficient-data, invalid-request and failed-job states are distinct. |
| P4.3 Descriptives | **Implemented; verified** | Numeric and categorical summaries, histograms, optional participant/session/trial aggregation, group/product/page stratification, denominators, source observation counts and units. AOI distributions are included. |
| P4.4 Inferential statistics | **Implemented; verified** | Pearson/Spearman correlation, independent Welch and paired participant tests, effect sizes, confidence intervals, missing-data policy, assumption/design warnings, Holm/Bonferroni/BH correction and association caveats. AOI pairwise comparisons use paired inference only for fully matched participants. |
| P4.5 Baselines and experiments | **Implemented; verified** | Mean/majority baseline, ridge/logistic experiments, explicit target/unit/predictors/exclusions/intended use, seed/model/data versions, participant/session grouped holdout, training-only imputation/normalization and deterministic ML fixture. Optional held-out predictions use opaque hashed row tokens. |
| P4.6 Modality fallback | **Implemented; verified** | best_available/gaze_only/non_gaze_only policies; missing gaze is never converted to zero; modality and dropped-gaze counts are surfaced. A dedicated fallback-vs-gaze-enhanced comparison only reports metric deltas for a matching held-out cohort. |
| P4.7 Evaluation and explanation | **Implemented; verified** | Held-out regression/classification metrics, baseline comparison, cluster-bootstrap intervals where sample supports them, Brier score and 10-bin expected/maximum calibration error summaries for binary classification, feature weights and optional small-cell-suppressed subgroup diagnostics. These are exploratory, not fairness certification. |
| P4.8 AOIs and heatmaps | **P4 analysis implemented; provider handshake pending** | AOI metrics map P3 `requested_aoi_id`. Heatmaps accept a separate versioned HeatmapInput provider payload matching canonical feature/session IDs; no `spatial` is read from FeatureRecord v1. The authorized P3 coordinate/geometry retrieval provider must be agreed and injected. |
| P4.9 Reports and evidence | **P4 result/report engine implemented; v1 mapping verified** | Reproducible report and provenance remain within the frozen v1 `results` object; aggregate-only CSV is exposed by the mountable router. |
| P4.10 UI, retrieval and failures | **Shared-app feature client implemented; shell integration pending** | A typed client covers analysis, result reads, paginated history, comparison and CSV export. It sends no FeatureRecords and uses same-origin credentials. The prior standalone demo server/page was removed; P2 console shell integration remains a shared task. |

## Architecture checklist mapping

The work-division master checklist assigns Person 4 categories Y–AE: analytical insights/recommendations (Y), statistical analysis (Z), ML experiment/result records (AA), modality-aware fallback (AB), evaluation/explainability (AC), visualizations/heatmaps (AD), and evidence-linked reporting (AE). The Architecture PDF separately lists a broader ML capability inventory under T and multimodal experiment inventory under U. Those are audited below rather than being treated as complete just because the P4.1–P4.10 starter outcomes are covered.

| Architecture ML capability | Status in this folder |
|---|---|
| T01 classification, T02 regression, T03 clustering | Implemented as multinomial logistic, Ridge and exploratory k-means. |
| T04 anomaly detection | Implemented with robust median/MAD candidate scoring and modality/quality gates. |
| T05 dimensionality reduction | Implemented as standardized PCA with two-component projection and opaque row tokens. |
| T06 feature selection | Implemented as exploratory univariate Pearson screening; not a substitute for nested training-fold selection. |
| T07 baselines, T09 evaluation | Implemented with mean/majority baselines and held-out metrics. |
| T08 ensembles | Implemented as transparent Ridge/mean regression or logistic/majority classification combinations. |
| T10 cross-validation | Implemented as grouped folds with fold-specific training preprocessing. |
| T11 hyperparameter configuration/tuning | Alpha-grid/model selection uses nested grouped cross-validation when the group sample supports it; smaller scopes return explicit insufficiency/bounded status. |
| T12 feature importance, T13 explainability, T14 predictions, T15 cluster generation | Implemented: model weights, qualified explanation labels, optional held-out predictions with hashed row tokens, and cluster assignments/profiles. |
| T19–T23 modality-aware model registry, modality requirements, gaze-free model declaration, fallback model registry, unified interface | Implemented as a versioned registry endpoint with task, modality, gaze-optional and fallback metadata; common experiment/result interface and modality enforcement apply to all registered models. Registry entries are code-declared, not runtime plugin-discovered. |
| T16 outlier generation | Implemented as labeled synthetic IQR-boundary stress cases; generated rows are not participant observations and are not merged into research data. |
| T17 sequence/temporal models | Conditional in the source architecture. This implementation provides within-session linear trend summaries when timestamped repeated measures exist; predictive sequence models remain unsupported because the architecture makes them conditional on justification. |
| T18 future deep-learning/advanced models | Explicitly future in the Architecture PDF; not implemented. |

| Architecture multimodal experiment capability | Status in this folder |
|---|---|
| U01/U03/U04 survey, behavior, interaction and response prediction | Implemented through generic supervised experiments plus explicit task recipes for survey/behavior, interaction, and response prediction. |
| U02 product-choice prediction | Implemented through a named product-choice classification recipe with caller-selected target and predictors. |
| U05 behavioral clustering | Implemented through exploratory k-means on selected numeric behavioral features; reports remain qualified as exploratory. |
| U06–U10 gaze-only, non-gaze baseline, gaze-augmented experiment and incremental comparison | Implemented with modality policy and matched-held-out-cohort comparison. |
| U11/U12 study-selectable capability and shared pipeline | Analysis type and model parameters are request-selectable; one shared local engine is used. |
| U13 model reuse | Implemented through persisted fitted model metadata and an authorized prediction endpoint for supported Ridge/logistic artifacts. |
| U22 automatic best valid model/result selection | Implemented by `model_selection`, which selects candidates inside inner grouped folds and evaluates the selection procedure on outer held-out groups when sample size permits. |
| U14 reusable outputs, U15–U21 modality detection/routing, modality/version/coverage and comparability metadata | Result persistence, modality detection, explicit fallback, model/version provenance and comparison caveats are implemented. |
| U23 common outcome across model variants | Both variants in a modality comparison use the same target. |

Architecture areas owned by P1/P2/P3 or the integrator, such as raw gaze/interaction ingestion, app shell/navigation, shared authorization, shared database/result store, and broad dashboard/platform features, remain outside this folder. The table does not imply those shared features are implemented.

## Integration still owned by the team boundary

P4 now provides the FastAPI router factory, typed console API client, SQLAlchemy 2.x PostgreSQL result repository and canonical P3 FeatureRecord adapter. The accepted Alembic migration, shared PostgreSQL session dependency, P2 authorization dependency, P3 retrieval provider, app router inclusion and optional spatial/geometry provider remain cross-owner integration decisions. Their concrete proposal is documented without editing shared wiring. P3 remains authoritative for raw gaze normalization, metric definitions and AOI measurement provenance. Synthetic fixtures are not research observations.

## Verification

The P4 integration tests validate canonical P3 non-gaze and generated gaze FeatureRecords, identity, missingness, modality, AOI mapping, a separate heatmap input, frozen request/result schemas, PostgreSQL metadata, and the injected FastAPI router. Engine tests continue covering known answers, statistics, grouped evaluation, fallback, AOI/heatmap behavior, reports, and advanced analytics. CI commands are `ruff check .`, `pytest --cov=services --cov-report=term-missing`, and `npm run typecheck`; see the review report for the executed results and external-service limits.
