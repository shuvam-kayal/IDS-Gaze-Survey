import assert from "node:assert/strict";
import test from "node:test";
import { analyticsStudyLabel, featureVersionState, uniqueAnalyticsStudies } from "../src/features/analytics/state.ts";

const experience = { experience_id: "experience-1", name: "Current workspace" };
const study = (study_id, status = "published", updated_at = "2026-01-01T00:00:00Z") => ({ study_id, experience_id: experience.experience_id, name: "Pinned", status, updated_at });

test("analytics studies retain real non-archived IDs and remove only duplicate IDs", () => {
  const result = uniqueAnalyticsStudies(
    [experience],
    new Map([[experience.experience_id, [study("study-1"), study("study-1"), study("draft-1", "draft", "2026-02-01T00:00:00Z"), study("archived-1", "archived")]]]),
  );
  assert.deepEqual(result.map(({ study: item }) => item.study_id), ["draft-1", "study-1"]);
  assert.equal(analyticsStudyLabel(result[1].study, experience), "Pinned — Current workspace [study-1]");
});

test("empty and available feature-set responses drive the selector state", () => {
  assert.deepEqual(featureVersionState(["1.0.0"]), { disabled: false, message: "Feature versions loaded." });
  assert.deepEqual(featureVersionState([]), { disabled: true, message: "No eligible persisted feature records are available for this Study." });
});
