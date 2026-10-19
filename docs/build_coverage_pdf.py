"""Build the companion Person 4 audit/coverage PDF. Requires reportlab."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "Person4_Requirements_Coverage_Audit.pdf"

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleCenter", parent=styles["Title"], alignment=TA_CENTER,
                          textColor=colors.HexColor("#17365D"), spaceAfter=8))
styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#17365D"),
                          spaceBefore=12, spaceAfter=6))
styles.add(ParagraphStyle(name="Cell", parent=styles["BodyText"], fontSize=8.5, leading=11, spaceAfter=0))
styles.add(ParagraphStyle(name="HeaderCell", parent=styles["Cell"], textColor=colors.white))
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.5, leading=11))


def P(text, style="Cell"):
    return Paragraph(text, styles[style])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.line(0.65 * inch, 0.55 * inch, 7.85 * inch, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.drawString(0.65 * inch, 0.36 * inch, "Person 4 isolated implementation | Source specifications unchanged")
    canvas.drawRightString(7.85 * inch, 0.36 * inch, f"Page {doc.page}")
    canvas.restoreState()


reqs = [
    ("P4.1 - Analysis contract and job lifecycle", "Request/result validation, version and study scope, statuses, warnings and limitations; queued/running/succeeded/failed jobs; persistence completes before succeeded; request ID idempotency. Local adapter contract and auth handoff documented."),
    ("P4.2 - Readiness and data quality", "Schema/version and scope validation; missingness, observed types/units, category balance/sparse cells, constants and IQR outlier candidates; filter inclusion/exclusion provenance; distinct no-data, insufficient-data, invalid-request and job-failure states."),
    ("P4.3 - Descriptive statistics", "Numeric and categorical counts, means, medians, spread/quantiles and missingness; category proportions and histograms; participant/session/trial/record aggregation; group/product/page stratification; denominators and source-observation counts."),
    ("P4.4 - Statistical inference", "Pearson/Spearman association, two-group independent Welch and paired participant tests, effect sizes and confidence intervals, multiplicity correction (Holm/Bonferroni/BH), missingness/design caveats and non-causal associative language."),
    ("P4.5 - Baselines and ML experiments", "Mean/majority baselines; regularized Ridge/logistic models and transparent ensembles; explicit task/target/features/exclusions/intended use; grouped participant/session holdout and grouped CV; training-only preprocessing; seeds, versions, missingness, optional held-out predictions with hashed row tokens."),
    ("P4.6 - Modality fallback", "best_available, gaze_only and non_gaze_only policies; no gaze imputation; modality/exclusion counts; fallback versus gaze-enhanced comparison only reports incremental metrics on matched held-out cohorts."),
    ("P4.7 - Evaluation and explanation", "Held-out metrics against baseline, cluster-bootstrap uncertainty when supported, Brier score and 10-bin ECE/MCE reliability estimates for binary classifiers, feature-weight explanation, optional subgroup audit with small-cell suppression; reports explicitly avoid calibration guarantees and fairness-certification claims."),
    ("P4.8 - AOI and heatmap analytics", "AOI dwell/TTFF summaries/distributions and pairwise comparisons; geometry/version/missing-AOI reporting; heatmap point/quality/coordinate/geometry gates; overlay only with stable normalized geometry; empty and unsafe-overlay states."),
    ("P4.9 - Evidence-linked reports", "Reproducible scope/filter/version/sample/modality/quality/uncertainty/limitations; automated suggestions cite result IDs and JSON paths; distinguishes suggestion from conclusion; JSON and aggregate-only CSV export routes."),
    ("P4.10 - Researcher UI and operational behavior", "Progress/failure/timeout handling, scope and version warnings, bounded retrieval with keyset-paginated history, comparison, filters, distributions, AOI/heatmap panels, readable evidence-linked reports and JSON/CSV export; synthetic fixture requires explicit opt-in."),
]

architecture = [
    ("Y - Insights/recommendations", "Evidence-linked descriptive suggestions for missingness, AOI dwell, interaction-friction metrics, modality coverage and gaze/interaction or attention/importance comparisons; context and non-causal limits stated."),
    ("Z - Statistical analysis", "Descriptive, correlation, group/paired tests, effects, uncertainty and correction."),
    ("AA - ML results", "Versioned experiment configuration/results, baselines, grouped evaluation and provenance."),
    ("AB - Modality fallback", "Explicit gaze/non-gaze paths and comparability rules."),
    ("AC - Evaluation/explainability", "Held-out performance, uncertainty, model explanation and qualified subgroup diagnostics."),
    ("AD - Visualizations", "Descriptive histograms, AOI distributions and quality/geometry-gated heatmaps."),
    ("AE - Reporting", "Evidence-linked outputs with scope, modality, sample size, uncertainty and limitations."),
]

ml_capabilities = [
    ("Implemented", "T01-T10: logistic classification, Ridge regression, k-means, robust anomaly candidates, PCA, feature screening, baselines, transparent ensembles, evaluation and grouped cross-validation; T12-T16: importance, explainability, hashed predictions, clusters and synthetic IQR-boundary stress cases."),
    ("Partial / bounded", "T11 model/alpha selection uses nested grouped cross-validation when sample groups support it; smaller scopes return bounded/insufficient status. T17 has within-session trend summaries only; predictive temporal models remain conditional on scientific justification."),
    ("Implemented with integration limit", "T19-T23 use a versioned, code-declared registry with task/modality/gaze-optional/fallback metadata, explicit modality routing and a unified result interface; runtime plugin discovery is not provided."),
    ("Future, not implemented", "T18 deep-learning/advanced models is explicitly identified as future in the Architecture PDF."),
]

multimodal = [
    ("Implemented", "U01-U05 offer task recipes for survey/behavior, product choice, interaction and response prediction plus exploratory behavioral k-means."),
    ("Implemented", "U06-U12 and U14-U23: modality-specific paths, matched-cohort comparison, one shared selectable engine, reusable model metadata with an authorizer-aware prediction route, modality provenance, nested model selection when sample sizes support it, and common outcome definitions."),
]


doc = SimpleDocTemplate(str(OUTPUT), pagesize=letter, rightMargin=.65*inch, leftMargin=.65*inch,
                        topMargin=.65*inch, bottomMargin=.75*inch, title="Person 4 Requirements Coverage Audit")
story = [P("Person 4 Requirements Coverage Audit", "TitleCenter"),
         P("IDS Gaze Survey | Statistical analytics, machine learning and research results", "Heading3"),
         P("This companion audit maps the Person 4 work-division requirements to the isolated implementation in this folder. It records the audit additions and the integration boundary. The supplied Work Division and Architecture PDFs remain unchanged.", "Small"),
         P("Audit result", "Section"),
          P("The implementation and README cover the explicit P4.1-P4.10 assignment and P4-owned work-division categories Y-AE. The review also added concrete Architecture T/U analytics capabilities; conditional predictive temporal models and future deep-learning remain bounded as specified. See the explicit status table on page 3.", "Small"),
         P("Work Division coverage (P4.1-P4.10)", "Section")]

rows = [[P("Assigned requirement", "HeaderCell"), P("Implementation coverage", "HeaderCell")]]
rows += [[P(a), P(b)] for a, b in reqs]
t = Table(rows, colWidths=[1.75*inch, 5.1*inch], repeatRows=1, hAlign="LEFT")
t.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")),
    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#CBD5E1")),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F1F5F9")]),
    ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
    ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
]))
story += [t, PageBreak(), P("Architecture checklist mapping", "Section"),
          P("The architecture PDF describes a broader platform. This table covers the analytics/results responsibilities assigned to P4; it does not reassign P1/P2/P3 or claim the whole platform is complete.", "Small")]
arows = [[P("Architecture category", "HeaderCell"), P("P4 implementation mapping", "HeaderCell")]] + [[P(a), P(b)] for a,b in architecture]
at = Table(arows, colWidths=[2.0*inch, 4.85*inch], repeatRows=1, hAlign="LEFT")
at.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("VALIGN", (0,0), (-1,-1), "TOP"), ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#CBD5E1")),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F1F5F9")]),
    ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
    ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
]))
story += [at, P("Integration boundary and assumptions", "Section"),
          P("All code and configuration for this assignment are isolated under Gaze_survey_Person_4. The shared repository, source PDFs and other owners' code were not edited. The screenshots show the starter repository but do not expose frozen shared schemas, authenticated API, shared Feature Store/result store or the P2 navigation shell. The local adapter therefore uses documented local contracts and SQLite, and requires P2/integrator connection for production. P3 remains authoritative for gaze normalization and AOI measurement provenance.", "Small"),
          P("The service uses synthetic fixtures only. It does not collect real participant data. Authentication/Study authorization and authorized exports must be supplied by the host application. Unsupported advanced methods and production guarantees remain documented limitations; the implementation does not claim the full architecture is complete.", "Small"),
          P("Verification record", "Section"),
          P("Verification performed for this audit: 32 standard-library unit tests passed; Python compileall passed; JSON contracts parsed; embedded researcher UI JavaScript passed node --check. Tests include new anomaly, PCA, feature-screening, synthetic outlier, temporal trend, grouped CV, model-selection and model-reuse paths. A 1,000-record descriptive/report performance smoke completed successfully.", "Small"),
          P("Specification sources", "Section"),
          P("IDS_Gaze_Survey_Detailed_Work_Division.pdf, Person 4 assignment and ownership/checklist sections (pp. 18-27). Architecture diagram and features list (1).pdf, analytics/statistics/ML/result store/dashboard/recommendation sections (pp. 16-22 and adjacent architecture feature lists). Exact page references refer to the supplied PDFs. This report is an implementation coverage audit, not a change to those specifications.", "Small")]

story += [PageBreak(), P("Broader architecture ML inventory: explicit status", "Section"),
          P("The architecture lists capability-library items beyond the detailed P4.1-P4.10 acceptance checklist. This status prevents those broader items from being mistaken as finished. Other architecture responsibilities assigned to P1/P2/P3 or the integrator remain outside this isolated deliverable.", "Small")]
mlrows = [[P("Status", "HeaderCell"), P("Architecture T items", "HeaderCell")]] + [[P(a), P(b)] for a,b in ml_capabilities]
mt = Table(mlrows, colWidths=[1.55*inch, 5.3*inch], repeatRows=1, hAlign="LEFT")
mt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17365D")),("VALIGN",(0,0),(-1,-1),"TOP"),
                        ("GRID",(0,0),(-1,-1),.35,colors.HexColor("#CBD5E1")),
                        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F1F5F9")]),
                        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
urows = [[P("Status", "HeaderCell"), P("Architecture U items", "HeaderCell")]] + [[P(a), P(b)] for a,b in multimodal]
ut = Table(urows, colWidths=[1.55*inch, 5.3*inch], repeatRows=1, hAlign="LEFT")
ut.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17365D")),("VALIGN",(0,0),(-1,-1),"TOP"),
                        ("GRID",(0,0),(-1,-1),.35,colors.HexColor("#CBD5E1")),
                        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F1F5F9")]),
                        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
story += [Spacer(1,8), mt, P("Multimodal/fallback experiments (Architecture U)", "Section"), ut,
          P("These are architecture inventory gaps, not silently claimed features. The detailed Work Division P4.1-P4.10 and owner checklist Y-AE mapping are documented separately above. Extending these advanced capabilities requires an explicit follow-up implementation and additional validation before research use.", "Small")]
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(OUTPUT)
