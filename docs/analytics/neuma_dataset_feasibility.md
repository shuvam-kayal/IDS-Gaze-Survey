# NeuMa dataset feasibility

Status: **blocked for implementation-level feasibility; no raw data downloaded and no training performed** (2026-11-05).

## Sources and license

- [NEMAR on004588](https://www.nemar.org/dataset/on004588), the NEMAR copy of
  [OpenNeuro ds004588](https://openneuro.org/datasets/ds004588), DOI
  `10.18112/openneuro.ds004588.v1.2.0`.
- The NEMAR page reports CC0 and 42 participants. It reports a published
  archive of about 0.5 GB/602 MB, so no archive or raw recording was fetched.
- The dataset paper is [NeuMa, Scientific Data 2023](https://www.nature.com/articles/s41597-023-02392-9).
  Attribution should retain the dataset DOI and the paper citation even though
  the repository reports CC0.

## Metadata access and files

The NEMAR landing page exposes the following small BIDS root entries (sizes are
the page's reported root-file sizes):

| Entry | Reported size | Status |
|---|---:|---|
| `dataset_description.json` | 594 B | Listed; content not returned by the fetcher |
| `participants.tsv` | 346 B | Listed; content not returned by the fetcher |
| `participants.json` | 79 B | Listed; content not returned by the fetcher |
| `README.md` | 882 B | Listed; content not returned by the fetcher |
| `task-unnamed_events.json` | 2 B | Listed; content not returned by the fetcher |
| `QuestionnaireResponses/` | directory | Listed; file names/contents not inspected |
| `sub-S01/` ... `sub-S44/` | participant directories | Listed; 42 participant IDs are reported by the page, with non-contiguous directory names |

The page reports 53 top-level entries and 83 of 84 recordings viewable, with
one failed `sub-S37` EEG viewer preparation. It labels the BIDS task as
`unnamed`. The exact sessions, runs, behavioral filenames, event columns,
questionnaire columns, and manifest checksums remain unverified.

The page provides these small-file URLs and access methods, but they were not
downloaded in this phase:

- `https://data.nemar.org/on004588/v1.0.0/dataset_description.json`
- `https://data.nemar.org/on004588/v1.0.0/participants.tsv`
- `https://data.nemar.org/on004588/v1.0.0/manifest.json`
- `https://data.nemar.org/on004588/v1.0.0/?format=json`
- `nemar dataset download on004588 --include ...` or a DataLad clone followed
  by `datalad get` for selected files.

## Confirmed experiment and labels

The official paper confirms a simulated grocery-brochure task with six brochure
pages. Participants browse products and select products they intend to buy.
The experiment records synchronized EEG, Tobii eye tracking, mouse clicks,
cursor positions, and markers. Eye tracking was recorded at 120 Hz after
9-point calibration. Product selection was derived from mouse streams and
cross-checked against questionnaire responses.

The paper states that browsing/selection ended before each participant filled
in a questionnaire. The questionnaire contains demographic and profiling
responses plus product-specific responses for selected products, including
selection reason, familiarity, and frequent-purchase information. It is not a
SUS/usability scale, and the exact response field names and encodings are not
confirmed without the files.

Confirmed target candidates:

- product selected: a binary product-level outcome inferred from clicks;
- number of products selected per brochure page: a page-level count;
- product-related questionnaire responses: labels only for selected products,
  and therefore unsuitable as predictors of selection without a separate
  leakage review.

The exact binary/multiclass encoding, product IDs, page IDs, timestamps, and
whether all products (selected and unselected) are represented in a joinable
table are **not verified**.

## Join and prediction feasibility

Likely join ingredients are subject ID (`S01`-style in the paper/page),
brochure page/product markers, synchronized timestamps, mouse click/cursor
streams, eye-tracker samples, and product bounding-box metadata. The paper
describes this join conceptually, including `segmentationLeaflet.m`, but the
actual BIDS event/behavior columns and file names were not accessible here.

The defensible first unit would be **participant × product exposure** if the
selected and unselected products can both be represented and each exposure is
bounded before the selection click. A page-level unit is a fallback if only
page counts are joinable. A participant-level unit would discard most of the
decision structure and should not be the first target.

For either repeated-measure unit, all rows for a participant must remain in
one participant-grouped train/test split. The 42 participants are the
independent groups; product rows are not independent samples for evaluation.

Potential numeric predictors after a small standard-library/Matlab-compatible
preprocessing step:

- gaze: valid-sample count/rate, fixation count and duration, dwell time in
  product AOI, time to first fixation, revisits, gaze dispersion, and missing-
  gaze indicators;
- mouse: click count/timing, cursor path length, movement duration, speed,
  pauses, and distance to product AOI;
- context available before the outcome: page/product/category/price metadata,
  only if the deployment scenario knows it in advance.

Raw XDF/eye-tracking/mouse streams cannot be passed directly to the existing
CSV adapter. A small preprocessing script must aggregate them into numeric
rows while preserving missing gaze as missing and retaining the subject ID as
the grouping column.

## Leakage audit

The strongest candidate is `selected` at the product-exposure level. Features
must be cut off before the selection click. Exclude the click that defines the
label, post-click cursor/gaze samples, marker-derived fields that encode the
selection, and any questionnaire response that is conditional on having
selected the product. Do not use product-specific “reason of selection”,
familiarity, or frequent-purchase responses as predictors of the same
selection label without a pre-registered causal justification; they are
post-outcome or selected-product-only information.

The paper's timeline supports gaze/mouse-before-questionnaire ordering, but it
does not by itself prove the exact event cutoff for every product row. That
must be validated from the event stream and marker timestamps after obtaining
small behavioral/marker files.

## Comparison with Mendeley

NeuMa is currently the better candidate for a **behavioral product-selection**
experiment: it has 42 reported participants, six-page/product structure,
synchronized gaze and mouse streams, and an outcome generated by selection.
Mendeley has locally verified 20 participants and 80 aggregate behavior rows,
but its 20 SUS rows have no participant key; the behavior/questionnaire join
and pre-SUS timing are therefore not validated. Mendeley remains the better
source for a SUS usability target only if an authoritative questionnaire-row
mapping is obtained.

NeuMa is not yet cleared for training. It becomes suitable after confirming
the small root metadata, selected behavioral/event files, product/page keys,
and the exact pre-click segmentation. The first exploratory model should be a
participant-grouped binary baseline (majority-class predictor) on
participant × product rows, with a simple numeric model only after join and
target-balance diagnostics pass. No training result is claimed here.

## Access attempts and outcomes

1. Opened the official NEMAR page: **successful**; confirmed CC0, 42
   participants, root inventory, BIDS task `unnamed`, download methods, and
   the reported failed `sub-S37` viewer preparation.
2. Opened the official OpenNeuro landing page: **page reachable**, but no
   readable file listing was returned by the fetcher.
3. Opened
   `https://data.nemar.org/on004588/v1.0.0/dataset_description.json`:
   **failed**, endpoint inaccessible to the fetcher.
4. Opened
   `https://data.nemar.org/on004588/v1.0.0/participants.tsv`:
   **failed**, fetcher rejected the `text/tab-separated-values` content type.
5. Opened the manifest and JSON directory listing URLs: **failed**, endpoint
   inaccessible to the fetcher.
6. Searched the official dataset documentation and paper: **successful** for
   experimental design, modalities, timing order, six brochure pages, product
   selection, and questionnaire scope. This did not substitute for inspecting
   actual BIDS columns.

## Decision and next step

**Decision: blocked, but promising and likely better than Mendeley for the
first behavioral UX experiment.** The remaining blocker is metadata/data-file
access, not a known scientific mismatch.

Next, obtain only `README.md`, `dataset_description.json`, `participants.tsv`,
`participants.json`, `task-*_events.json`, the questionnaire directory's small
files, and one or two subjects' behavioral/marker metadata. Verify exact keys
and cutoff timestamps before writing a dataset-specific adapter preprocessing
script. Do not fetch the 0.5 GB archive or EEG files for this UX experiment.
