# Gaze and non-gaze fallback

Research consent and browser camera permission are separate. Never activate capture before informed consent; provide visible status and a stop control. Stop on withdrawal, session end or permission loss.

In gaze mode, P1 captures only under consent. P3 normalizes external estimator output to canonical GazeRecord, tracks calibration/quality, maps samples to versioned AOIs and computes gaze features.

When denied, unavailable or interrupted, participation continues with surveys, timing, interactions, trial lifecycle and permitted AOI exposure. Do not store frames as fallback. P3 records reason-coded missingness; missing is not zero. P4 uses compatible non-gaze analysis and labels modality/limitations. Webcam gaze is an attention proxy, not cognitive ground truth.
