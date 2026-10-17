/**
 * Test-only mock-P1 inputs. This does not access a camera or represent
 * participant observations. It supplies deterministic provider predictions
 * and the existing study/trial boundary values to adapter/pipeline tests.
 */

export function createMockP1Scenario({ consentGranted = true, outcome = "valid" } = {}) {
  const predictions = outcome === "missing"
    ? [null, { x: 25, y: 25 }]
    : outcome === "initialization_failure"
      ? []
      : [{ x: 25, y: 25 }, { x: 26, y: 25 }, { x: 25, y: 26 }];
  return {
    test_only: true,
    consent_granted: consentGranted,
    outcome,
    session_id: "mock-session-1",
    experience_id: "mock-experience-1",
    session_bootstrap: {
      schema_version: "1.0.0",
      session_id: "mock-session-1",
      experience_id: "mock-experience-1",
      participant_id: null,
      experience_config_version: "mock-experience-v1",
      eligible_studies: [
        { study_id: "mock-study-a", config_version: "mock-config-a-v1", aoi_set_version: "mock-aoi-a-v1", question_set_version: "mock-questions-a-v1" },
        { study_id: "mock-study-b", config_version: "mock-config-b-v1", aoi_set_version: "mock-aoi-b-v1", question_set_version: "mock-questions-b-v1" },
      ],
      privacy_notice_version: "mock-privacy-v1",
      research_consent_version: "mock-consent-v1",
      camera_capture_supported: true,
      issued_at: "2026-01-01T09:00:00Z",
      expires_at: "2026-01-01T11:00:00Z",
    },
    studies: [
      {
        study_id: "mock-study-a",
        trial_id: "mock-trial-a",
        aoi_set_version: "mock-aoi-a-v1",
        window_start: "2026-01-01T10:00:00.000Z",
        window_end: "2026-01-01T10:00:05.000Z",
      },
      {
        study_id: "mock-study-b",
        trial_id: "mock-trial-b",
        aoi_set_version: "mock-aoi-b-v1",
        window_start: "2026-01-01T10:00:05.000Z",
        window_end: "2026-01-01T10:00:10.000Z",
      },
    ],
    viewport: { width: 100, height: 100 },
    geometry_snapshots: [
      { snapshot_id: "mock-geometry-a", session_id: "mock-session-1", study_id: "mock-study-a", aoi_set_version: "mock-aoi-a-v1", viewport_width_px: 100, viewport_height_px: 100, rectangles: [{ aoi_id: "mock-target-a", left_px: 0, top_px: 0, right_px: 50, bottom_px: 50, priority: 1 }] },
      { snapshot_id: "mock-geometry-b", session_id: "mock-session-1", study_id: "mock-study-b", aoi_set_version: "mock-aoi-b-v1", viewport_width_px: 100, viewport_height_px: 100, rectangles: [{ aoi_id: "mock-target-b", left_px: 50, top_px: 0, right_px: 100, bottom_px: 50, priority: 1 }] },
    ],
    predictions,
    interaction_events: [
      { schema_version: "1.0.0", event_id: "mock-click-1", experience_id: "mock-experience-1", study_ids: ["mock-study-a"], session_id: "mock-session-1", event_type: "interaction.click", occurred_at: "2026-01-01T10:00:01Z", payload: { target: "mock-button" } },
      { schema_version: "1.0.0", event_id: "mock-scroll-1", experience_id: "mock-experience-1", study_ids: ["mock-study-b"], session_id: "mock-session-1", event_type: "interaction.scroll", occurred_at: "2026-01-01T10:00:06Z", payload: { scroll_delta_px: 40 } },
    ],
    survey_events: [{ schema_version: "1.0.0", event_id: "mock-survey-1", experience_id: "mock-experience-1", study_ids: ["mock-study-a", "mock-study-b"], session_id: "mock-session-1", event_type: "survey.completed", occurred_at: "2026-01-01T10:00:09Z", payload: { test_only: true } }],
    survey: { presentation: "end_of_session", test_only: true },
  };
}
