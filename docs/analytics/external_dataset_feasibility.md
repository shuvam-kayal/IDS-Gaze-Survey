# External dataset feasibility for predictive UX

Status: feasibility review only; no datasets downloaded and no training performed.

The review uses the official dataset landing pages, repository metadata, and the
associated data descriptors. “Confirmed” means stated by those sources. Exact
column names, row counts, and joins marked “inspect” require downloading or
requesting only the small metadata files; they are not inferred from abstracts.

## Recommendation

Use these two datasets for the first experiment, in separate dataset-specific
experiments rather than one pooled model:

1. **Eye-Tracking Enhanced E-Shopping Website** (Mendeley DOI
   [10.17632/3c68smp2km.1](https://data.mendeley.com/datasets/3c68smp2km/1)):
   closest confirmed match to the product-page study because it contains
   operation data, eye tracking, and SUS usability data.
2. **NeuMa / OpenNeuro ds004588 / NEMAR on004588** ([NEMAR landing page](https://www.nemar.org/dataset/on004588)):
   complementary e-commerce evidence with eye tracking, mouse data,
   questionnaires, and intended-product-selection outcomes.

The [Scientific Data website interaction/emotion dataset](https://www.nature.com/articles/s41597-025-06079-1)
is the best non-gaze interaction benchmark, but its labels are automatically
inferred emotions rather than usability or satisfaction. Keep it as a later
non-gaze baseline, not as the first page-effectiveness target source.

Do not pool these datasets initially. Their page/task definitions, labels,
sampling, and measurement instruments differ. Train and evaluate within each
dataset, then compare feature families and limitations.

## Candidate review

| Dataset | Official access, license, and confirmed files | Participants and unit | Confirmed signals/labels | Adapter fit |
|---|---|---|---|---|
| **NeuMa** | NEMAR/OpenNeuro; NEMAR lists CC0, OpenNeuro DOI `10.18112/openneuro.ds004588.v1.2.0`, NEMAR DOI `10.82901/nemar.on004588`, and a 0.5 GB archive. Access is through `nemar dataset download on004588`, DataLad/git-annex, or direct manifest files. BIDS plus annexed files are confirmed; exact eye-tracking and questionnaire filenames require manifest/README inspection. | 42 participants. Participant-level recordings with product/brochure and session/trial structure; exact join keys require inspection. | Eye tracking, computer mouse, demographic/profiling/product questionnaires, and product-intention selection are confirmed. A usability/SUS label is not confirmed. | **Small preprocessing script required**: extract/aggregate eye movements and mouse events, join questionnaire/product-choice data, then emit one participant × task/product row as CSV. |
| **Mendeley e-shopping** | Official Mendeley page; CC BY 4.0; “Download All.” Four files are confirmed: experiment script, analysis script, SUS scale data, and behavior data containing operation and eye-tracking data. Exact filenames, formats, and row counts require download inspection. | Participant-level experiment is implied by SUS and behavior files, but participant count and exact analysis unit are not stated on the landing page; inspect files/scripts. | Eye tracking, operation data, SUS questionnaire, usability/HCI context confirmed. Product-selection/completion outcome is not confirmed from the landing page. | **Small preprocessing script required**: identify participant/trial keys, aggregate behavior and gaze, calculate/use SUS total, and export a numeric CSV. |
| **Web Design Prototypicality: eCommerce** | [Harvard Dataverse DOI](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/9FKSQI); CC0 1.0 Universal is reported by the catalog record. Access is through the Dataverse dataset and nested domain datasets. | Primarily webpage-level ratings/features. The associated descriptor reports 1,530 participants and more than 3,000 webpages across domains; the released analysis includes raw and aggregated ratings. | No gaze or interaction logs. Survey/page ratings include prototypicality, aesthetics, perceived ease-of-use/usability, and trustworthiness. No task completion or product-selection outcome. | **CSV likely usable after selection**, but page-level aggregation means participant-wise modeling may not be possible for the released aggregate tables. Inspect raw versus aggregated files and computed feature columns first. |
| **ETTAC website interaction/gaze** | [Zenodo record 20764568](https://zenodo.org/records/20764568); open record, but rights state copyright © 2026 Fabian Engl rather than a permissive reuse license. Files confirmed: `Dataset_EyeMovement_Level.csv` (50.9 MB) and `UserInputs.xlsx` (230.1 kB); record data volume is listed as 11.8 GB. | 121 participants across six websites; participant/stimulus/task-level eye-movement rows. | Gaze fixations/saccades and coordinates/durations. `UserInputs.xlsx` includes reported difficulty 1–10, right-click timestamps, elapsed time, and completion encoded by zero timestamps. No broader questionnaire is confirmed. | **Preprocessing required**: aggregate eye movements by participant × stimulus × task window; convert/join XLSX metadata; emit CSV. Do not use until licensing/reuse conditions are clarified. |
| **Website interactions and emotions** | [Scientific Data descriptor](https://www.nature.com/articles/s41597-025-06079-1); data is available from [Figshare DOI 10.6084/m9.figshare.28489601](https://doi.org/10.6084/m9.figshare.28489601). The paper confirms free access; the Figshare dataset license still needs verification before redistribution. | 19 real users, observed over 30 days. Both raw interaction-event rows and user/time-window aggregate rows exist. | Non-gaze mouse, scroll, keyboard, URL and timing features. Emotion labels include joy, fear, disgust, sadness, anger, surprise, contempt, valence, and engagement, inferred by Affectiva. No survey/usability/satisfaction questionnaire or product-selection outcome is confirmed. | `aggregate.csv` can likely be mapped after inspection; raw `interactions.csv` needs aggregation. Use `user_id` as participant/group ID and website/time-window as the analysis unit. |

## Feature and label assessment

| Dataset | Gaze | Non-gaze interaction | Survey/questionnaire | UX/usability/satisfaction label | Completion/product outcome |
|---|---:|---:|---:|---:|---:|
| NeuMa | Yes | Mouse | Yes | Product-related questionnaire confirmed; usability label not confirmed | Intended product selection: yes |
| Mendeley e-shopping | Yes | Operation data | SUS: yes | SUS usability score: yes | Not confirmed |
| Web Design Prototypicality | No | No interaction log | Page-rating questionnaires | Usability/ease-of-use, aesthetics, trustworthiness: yes | No |
| ETTAC | Yes | Task completion/right-click metadata | Difficulty rating only | Difficulty is a task label, not a full usability scale | Completion: yes |
| Scientific Data emotions | No | Mouse, scroll, keyboard, URL/timing | No questionnaire confirmed | Emotion/engagement labels, not usability satisfaction | No |

The first two rows in the table are participant-level sources. The
prototypicality dataset is primarily a stimulus/page-level outcome dataset,
even though raw participant ratings are also reported. ETTAC is participant ×
website/task/eye-movement data. The Scientific Data dataset contains both
participant-level identities and repeated event/time-window rows; it is not one
row per participant without aggregation.

## Initial prediction design

### Primary target

Start with **post-exposure usability/effectiveness as a continuous target**:

- Mendeley: SUS total or a documented SUS-derived score, pending confirmation
  of the scale file and scoring script.
- NeuMa: use a documented product-selection/intended-to-buy binary outcome as a
  separate behavioral target if the exact column and timing are confirmed.

Do not combine these labels into one target. SUS is perceived usability;
product selection is a behavioral decision outcome.

### Candidate feature mapping

After file inspection, map one row to one participant × page/product/task
exposure:

- Gaze: fixation count/duration, dwell/attention time, time to first fixation,
  revisits, transitions, scan-path summaries, and missingness indicators.
- Non-gaze: click count, scroll distance, task duration, cursor/mouse activity,
  and completion/time-to-completion where measured before the target.
- Context: page/product/stimulus condition and task condition only when they are
  available at prediction time and encoded without using target-derived values.

The existing adapter can consume the final numeric CSV with participant ID,
optional session ID, target, and predictors. The raw source files require a
small dataset-specific aggregation/join script first.

### Leakage rules

- Exclude all SUS items and SUS total when predicting SUS total; otherwise the
  task is a deterministic reconstruction of the questionnaire.
- Exclude product-choice questionnaire items, post-choice responses, or any
  field used to define the intended-buy label when predicting product choice.
- Use only gaze/interaction observations from before the target timestamp or
  before task completion.
- Keep page/product identity as a grouping or condition variable unless the
  intended deployment explicitly knows that identity.
- Split by participant. If repeated sessions/tasks exist, keep all rows for a
  participant in one fold; never fall back to row-level random splitting.
- Preserve unavailable gaze as missing; do not convert missing eye tracking to
  zero.

## Domain mismatch and interpretation limits

- NeuMa and Mendeley are e-shopping studies, but they use different products,
  page designs, tasks, instruments, and hardware. They support UX feature
  feasibility, not direct performance claims for the IDS product-page study.
- ETTAC uses information-seeking on association/water-provider sites, not
  product pages; difficulty and completion may transfer as task-effectiveness
  proxies, but not as shopping satisfaction.
- The prototypicality dataset evaluates first impressions of screenshots/pages,
  not interactive task behavior or gaze.
- The Scientific Data dataset is in-the-wild browsing with automatically
  inferred emotion, not researcher-administered usability or satisfaction.
- Cross-dataset comparisons should be descriptive and feature/label-specific;
  they should not be interpreted as a universal UX model.

## Exact next steps before training

1. Download only metadata/small files first: Mendeley archive metadata/scripts,
   NeuMa `participants.tsv`, `dataset_description.json`, manifest and README,
   and ETTAC `UserInputs.xlsx` plus the CSV header/preview.
2. Verify licenses for the Mendeley, NeuMa, ETTAC, and Figshare sources and
   record attribution requirements. ETTAC reuse is blocked pending clarification
   of its copyright-only rights statement.
3. Produce a dataset-specific data dictionary: row unit, participant/session
   keys, timestamps, page/product/task key, missingness, and target timing.
4. Write one small preprocessing script per selected source that emits a
   temporary numeric CSV for `services/analytics/external_dataset.py`; do not
   alter FeatureRecord v1.
5. Run adapter diagnostics and leakage review on the resulting CSVs. Confirm
   participant counts, target balance, missing gaze rates, and duplicate group
   behavior before invoking any existing P4 model code.
6. Only then define the first training request and run grouped cross-validation;
   no training result is claimed by this feasibility review.

## Sources

- [NEMAR NeuMa/on004588](https://www.nemar.org/dataset/on004588)
- [Mendeley e-shopping dataset](https://data.mendeley.com/datasets/3c68smp2km/1)
- [Harvard Dataverse eCommerce prototypicality DOI](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/9FKSQI)
- [Web design dataset descriptor](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823051/)
- [ETTAC Zenodo record](https://zenodo.org/records/20764568)
- [Scientific Data website interaction/emotion descriptor](https://www.nature.com/articles/s41597-025-06079-1)
- [Scientific Data Figshare record](https://doi.org/10.6084/m9.figshare.28489601)
