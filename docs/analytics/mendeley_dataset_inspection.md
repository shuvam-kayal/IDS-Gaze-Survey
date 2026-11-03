# Mendeley e-shopping dataset inspection

Status: **blocked at file acquisition; no training performed**.

This report records only facts visible on the official landing page or in the
official Mendeley API documentation. No participant-level file contents are
claimed because the actual dataset files could not be retrieved from this
environment.

## Source, license, and access

- Official landing page: [Mendeley Data dataset 3c68smp2km, version 1](https://data.mendeley.com/datasets/3c68smp2km/1).
- DOI: `10.17632/3c68smp2km.1`.
- Title: “Supplemental materials: Eye-Tracking Enhanced Human-Computer
  Interaction on E-Shopping Website: A Preliminary Study on Physiological
  Mechanism”.
- Contributor shown by the landing page: Weizhe Li.
- Published: 31 January 2020, version 1.
- License shown by the landing page: **CC BY 4.0**. Attribution is required;
  the citation and license should be retained with any derived data.
- The landing page exposes a “Download All” control and states that the
  material is reproducible with Python 3.6/Jupyter.
- The page describes four logical files/components:
  1. experiment script;
  2. data analysis script;
  3. scale data containing the SUS questionnaire;
  4. behavior data containing operation and eye-tracking data.

The official [Mendeley Data API documentation](https://data.mendeley.com/api/docs/)
documents public dataset metadata, file-list, snapshot, per-file metadata, and
download-redirect endpoints. The dataset identifier for those endpoints is
`3c68smp2km`, version `1`.

## Acquisition diagnostics and blocker

The following read-only attempts were made; no archive or data file was saved:

1. Opened the official landing page through web access. The page exposed the
   four logical components and license, but not filenames, file sizes, headers,
   or download URLs in the accessible HTML.
2. Attempted the documented file-list endpoint:

   ```text
   https://api.data.mendeley.com/datasets/publics/3c68smp2km/files?version=1
   ```

   The sandbox failed DNS resolution for `api.data.mendeley.com`.
3. Retried the same official endpoint with an approved read-only external
   request. The connection was reset by the remote host before a response was
   received.
4. Attempted a browser-based inspection of the official page. Browser
   automation stopped because it could not establish the current browser URL
   with sufficient confidence for the safety policy.

Because neither file metadata nor file bytes were obtained, the following
items remain **unverified** rather than inferred:

- actual filenames, sizes, formats, and encodings;
- actual CSV/Excel/script headers and data dictionaries;
- participant IDs and independent participant count;
- trial/task/page IDs and their counts per participant;
- timestamps and participant/task join keys;
- exact SUS item columns, reverse-scoring rules, and whether a SUS total exists;
- exact gaze and operation fields;
- questionnaire timing relative to gaze/operation observations;
- missingness, duplicates, incomplete participants, and row-unit structure.

## Inspection result

No actual dataset file was inspected. Accordingly:

| Requested diagnostic | Result |
|---|---|
| Participant count | Not available; must inspect scale/behavior files |
| Trials/tasks/pages per participant | Not available |
| SUS response fields/scoring | Only “SUS questionnaire” is confirmed; item names and scoring are not available |
| Existing SUS total | Not verified |
| Gaze fields | Eye-tracking data is confirmed at landing-page level; field names not verified |
| Interaction fields | Operation data is confirmed at landing-page level; field names not verified |
| Join keys | Not verified |
| Before/after questionnaire timing | Not verified |
| Missingness/duplicates/incomplete participants | Not assessed |
| Defensible analysis row unit | Not determined |

The earlier feasibility report’s statement that this dataset contains eye
tracking, operation data, and SUS data remains supported by the official page;
all finer-grained schema claims remain pending.

## Feasibility and leakage decision

The dataset is **not yet cleared for a valid predictive usability experiment**.
It may become suitable if the downloaded files establish all of the following:

1. a stable participant identifier shared by behavior and SUS data;
2. a defensible observation unit, preferably participant × task/page or
   participant-level exposure, with repeated rows retained for grouped splits;
3. SUS item responses and a reproducible scoring rule;
4. behavior and gaze observations occurring before the SUS response, or a clear
   exposure-level boundary before questionnaire completion;
5. enough independent participants for participant-grouped holdout/CV;
6. no target-derived fields in the behavior or analysis outputs.

If SUS is a single post-study score, repeating that same score across multiple
task/page rows would not create independent labels. In that case the defensible
first unit is participant-level, or a participant-level aggregation of all
pre-questionnaire behavior/gaze. A participant × page/task model is valid only
if the source contains page/task-specific usability labels or a justified
assignment of the score to each exposure; this cannot be assumed.

## Proposed adapter mapping, pending file inspection

The existing adapter is [services/analytics/external_dataset.py](../../services/analytics/external_dataset.py).
The eventual preprocessing output should be a temporary CSV with a mapping
like this, after the source schema is verified:

| Adapter setting | Proposed value |
|---|---|
| `dataset_id` | `mendeley-e-shopping-v1` |
| `participant_column` | Actual participant column discovered in the files; do not assume a name |
| `session_column` | Actual task/page/session key if present; otherwise omit and aggregate at participant level |
| `target_column` | A newly constructed `sus_total` only after confirming item scoring |
| `predictor_columns` | Pre-questionnaire numeric gaze/operation aggregates only |
| `modality` | Do not use one global modality if mixed; encode gaze feature values with gaze metadata during preprocessing |
| `source` | Official DOI/landing-page URL |

Exclude all SUS item columns, any existing SUS total, post-questionnaire
responses, and any analysis output derived from SUS. Do not replace missing gaze
with zero; preserve it as missing and include an explicit availability/count
feature only when that feature is computed from pre-questionnaire capture.

## Smallest defensible first experiment after unblocking

1. Download only the four official components once access works; do not use a
   duplicate archive.
2. Read scripts and headers; identify the participant and exposure join keys.
3. Reproduce SUS scoring from the official analysis script, recording the exact
   item list and reverse-scored items.
4. Aggregate only pre-SUS behavior/gaze observations to one row per participant
   unless exposure-level SUS labels are actually present.
5. Run the external adapter diagnostics and reject rows with missing target or
   missing group ID.
6. Use participant-grouped holdout/CV with the existing P4 baseline model
   (training mean for continuous SUS) before any ridge model.
7. Report participant count, target distribution, missing gaze, and the exact
   eligible predictor list before training.

No model training or training result is claimed in this phase.

## Reproducible inspection script

No script was added because no local dataset files were acquired and the file
formats are not known. Once the official files are available locally, the
smallest safe next change is a standard-library inspection script under
`scripts/analytics/` that accepts explicit file paths, prints headers/counts/
missingness/duplicate summaries, and never writes raw rows or uploads data.

## Unresolved questions

- What are the exact four filenames and formats?
- What is the independent participant count after incomplete records are
  excluded?
- Are there task/page/trial identifiers shared across operation, gaze, and SUS?
- Is SUS scored per participant, per task, per website, or only once after the
  study?
- Does the analysis script use a nonstandard SUS scoring or filtering rule?
- Are gaze and operation timestamps on a common clock and bounded before the
  questionnaire?
- Are any existing “analysis” columns target-derived?
- Are there duplicate event rows or incomplete participants?

## Commands/outcomes

```text
Get-Content docs/analytics/external_dataset_feasibility.md
Get-Content services/analytics/external_dataset.py
```

Outcome: existing feasibility assumptions and adapter contract reviewed.

```text
Invoke-WebRequest https://api.data.mendeley.com/datasets/publics/3c68smp2km/files?version=1
```

Outcome: sandbox DNS failure: `No such host is known`.

```text
curl.exe -L --http1.1 -A "Mozilla/5.0" \
  "https://api.data.mendeley.com/datasets/publics/3c68smp2km/files?version=1"
```

Outcome: sandbox DNS failure; approved external retry ended with `Recv failure:
Connection was reset`.

No tests were run because this phase changed documentation only and added no
code.
