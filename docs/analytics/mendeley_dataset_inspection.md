# Mendeley e-shopping dataset inspection

Status: **local inspection completed; no training performed**.

This report records only facts visible on the official landing page or in the
official Mendeley API documentation. No participant-level file contents are
claimed because the actual dataset files could not be retrieved from this
environment.

The dataset was subsequently supplied locally by the user and inspected from:

```text
C:\Users\infos\Downloads\Supplemental materials Eye-Tracking Enhanced Human-Computer Interaction on E-Shopping Website A Preliminary Study on Physiological Mechanism
```

The findings below supersede the earlier acquisition-blocker section where
local file contents are available.

## Actual local files inspected

All files are under the downloaded directory's `New folder` subdirectory:

| File | Size | Format | Confirmed contents |
|---|---:|---|---|
| `New folder/Experiment.ipynb` | 17,221 bytes | Jupyter notebook JSON | Participant setup, EyeLink 1000/II capture configuration, task/control trial code |
| `New folder/Analysis.ipynb` | 529,780 bytes | Jupyter notebook JSON | R analysis code for SUS and behavior summaries |
| `New folder/behavior.csv` | 4,248 bytes | UTF-8 CSV | 80 behavior rows, 11 columns |
| `New folder/questionnaire.csv` | 950 bytes | UTF-8 CSV | 20 rows, 10 SUS item columns |

No Excel, standalone JSON, EDF, or other raw eye-tracker files were present
in the supplied directory. The available gaze data is already summarized in
`behavior.csv`; raw gaze samples are not available in this local download.

## Actual schemas and repeated-measure structure

`behavior.csv` columns, in file order:

```text
sub, trial, website, duration, operation, blink, fixation,
blink_interval, fixation_count, fixed_duration, fixed_operation
```

Confirmed values/counts without printing participant IDs:

- 80 rows.
- 20 distinct `sub` values; all have 4 rows.
- `trial`: `With_sys` = 40, `Without_sys` = 40.
- `website`: `JD` = 40, `Tmall` = 40.
- Each `trial × website` cell contains 20 rows.
- No blank `sub` values.
- No duplicate full rows.
- No duplicate `(sub, trial, website)` keys.
- No timestamp column exists in the CSV.
- Numeric behavior fields are complete across all 80 rows.
- Observed ranges: `duration` 22–138; `operation` 9–47; `blink` 3–73;
  `fixation` 15–426; `blink_interval` 1–19; `fixation_count` 0.31–7.98;
  `fixed_duration` 22–129.19; `fixed_operation` 7–44.

`questionnaire.csv` columns, in file order:

1. `I think that I would like to use the system frequently`
2. `I found the system to be simple`
3. `I thought the system was easy to use`
4. `I think that I could use the system without the support of a technical person`
5. `I found the various functions in the system were well integrated`
6. `I thought there was a lot of consistency in the system`
7. `I would imagine that most people would learn to use the system very quickly`
8. `I found the system very intuitive`
9. `I felt very confident using the system`
10. `I could use the system without having to learn anything new`

All 20 × 10 questionnaire cells are numeric and non-missing. There are no
participant, trial, website, page, timestamp, or session columns in this file.
The 20 rows therefore cannot be keyed to the 20 `sub` values from
`behavior.csv` using a validated join.

## Source scripts and SUS scoring

`Experiment.ipynb` confirms:

- participant number, gender, and age are entered interactively;
- EyeLink configuration uses 250 Hz sampling and stores fixation, saccade,
  blink, message, button, gaze, gaze-resolution, status, and head-target data
  in EDF during collection;
- experiment messages include `Record_<website>_Start_at_<time>`, matching end
  messages, and analogous `Control_<website>` messages;
- the downloaded `behavior.csv` is an aggregate output, not the EDF/raw gaze
  stream.

`Analysis.ipynb` reads `questionnaire.csv` and uses:

```r
for (i in eye_scale[1:10,1:10]) {
    sus_list[length(sus_list) + 1] = ((sum(i) - 10) * 2.5)
}
```

This source calculation produces 10 values—one per questionnaire column over
the first 10 questionnaire rows—not one SUS score per participant. It also
does not apply standard SUS odd/even scoring (`odd - 1`, `5 - even`). The
notebook then runs `psych::alpha(eye_scale)` but does not create or persist a
participant-level SUS total.

Using the verified item order and standard SUS scoring only as a diagnostic,
the 20 reconstructed participant-row scores have range 35–60, mean 48.75,
and median 50. These are not training results and should not be treated as
source-provided labels until the questionnaire-row-to-participant mapping is
confirmed.

The notebook’s literal formula over its first 10 rows produces 10 values with
range 55–82.5 and mean 72.25. This confirms that the source notebook’s
`sus_list` is not a valid participant-level target.

## Join and timing audit

The behavior data can be grouped by participant, trial, and website. The SUS
data cannot be joined to those groups because it has no participant or exposure
key. Equal row counts (20 behavior participants and 20 questionnaire rows) are
not sufficient evidence of row-order correspondence.

The supplied behavior CSV has no timestamps. The experiment notebook records
timestamps inside EyeLink messages, but those EDF files are not present. The
notebooks also do not show questionnaire administration or a persisted event
that ties questionnaire completion to the behavior rows. Therefore:

- gaze/operation-before-SUS timing is **not confirmed from the supplied files**;
- post-questionnaire contamination cannot be ruled out from the aggregate CSV;
- per-task or per-page SUS labels are **not present**;
- a repeated SUS label across the four behavior rows per participant would be
  a duplicated outcome, not four independent labels.

## Missingness, duplicates, and completeness

- `behavior.csv`: no missing values in the observed 80 rows; all 20
  participants have the expected four repeated rows; no full-row or
  participant/trial/website-key duplicates.
- `questionnaire.csv`: no missing values in the observed 200 cells; 20 rows
  of equal width; no duplicate full questionnaire rows.
- Cross-file completeness cannot be validated because the questionnaire lacks
  a participant key.
- Raw gaze missingness, calibration loss, blinks at sample level, and EDF
  integrity cannot be assessed because raw EDF files are absent.

## Feasibility decision and modeling unit

The dataset is **not cleared for a valid SUS prediction experiment yet**.

The defensible unit, if the questionnaire row order can be authoritatively
matched to `sub` through source documentation or an additional supplied key,
is **participant-level**, not participant × task/page. The behavior data has
four repeated exposures per participant, while SUS appears to be one
post-study questionnaire row per participant. Aggregate the four pre-SUS
behavior rows into one participant row and retain participant IDs for grouped
evaluation.

If an authoritative join cannot be established, do not attach SUS scores to
participants or train a predictive model. The dataset can still support
descriptive behavior analysis by `sub × trial × website`.

## Leakage audit and provisional mapping

Potential target: a correctly scored participant-level `sus_total`, constructed
from the ten questionnaire items only after the row join is validated.

Eligible predictors, subject to timing confirmation:

- aggregated pre-SUS `duration`, `operation`, `blink`, `fixation`,
  `blink_interval`, `fixation_count`, `fixed_duration`, and `fixed_operation`;
- condition/page context (`trial`, `website`) only if known at prediction time;
- missingness/availability indicators only if derived from pre-SUS data.

Explicitly exclude:

- all ten SUS item columns;
- the source notebook’s `sus_list` and any other SUS-derived value;
- any questionnaire response or post-questionnaire analysis field;
- any behavior recorded after questionnaire completion;
- participant ID as a predictor.

The existing adapter can represent the eventual participant-level CSV with:

```text
dataset_id       = mendeley-e-shopping-v1
participant_col  = sub
session_col      = optional participant exposure/session key, if documented
target_col       = sus_total
predictors       = pre-SUS numeric behavior aggregates plus approved context
```

This mapping must not be used until the questionnaire join and timing are
resolved. The adapter contract and FeatureRecord v1 remain unchanged.

## Recommended next step

Obtain one of the following before any training:

1. source documentation that states questionnaire row order maps to `sub`; or
2. an additional participant-keyed questionnaire file; or
3. raw/session metadata that establishes the mapping and questionnaire timing.

Then create a small preprocessing step that validates the join, computes
standard SUS scores, aggregates the four behavior rows per participant, and
emits a temporary CSV for the existing external adapter. The first experiment
should use the participant-grouped mean baseline only; no model result is
justified by the current unvalidated join.

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

## Historical acquisition diagnostics

The following records the earlier network-access blocker. It no longer blocks
local inspection, but it explains why the supplied directory was used.

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

Before the local directory was supplied, neither file metadata nor file bytes
could be obtained remotely. The following items were therefore initially
unverified; their current status is resolved in the actual-inspection sections
below where local contents support it:

- actual filenames, sizes, formats, and encodings;
- actual CSV/Excel/script headers and data dictionaries;
- participant IDs and independent participant count;
- trial/task/page IDs and their counts per participant;
- timestamps and participant/task join keys;
- exact SUS item columns, reverse-scoring rules, and whether a SUS total exists;
- exact gaze and operation fields;
- questionnaire timing relative to gaze/operation observations;
- missingness, duplicates, incomplete participants, and row-unit structure.

## Earlier remote-only inspection result

The earlier remote-only inspection did not inspect actual dataset files. The
local inspection above and below supersedes it where applicable:

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
