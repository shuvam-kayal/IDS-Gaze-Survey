"""P3-owned non-gaze features; missing gaze is never imputed as zero."""

from typing import Any


def build_non_gaze_features(
    events: list[dict[str, Any]], *, survey_completion_ratio: float | None = None
) -> dict[str, int | float | None]:
    clicks = sum(1 for event in events if event.get("event_type") == "interaction.click")
    scroll = sum(
        float(event.get("payload", {}).get("scroll_delta_px") or 0)
        for event in events
        if event.get("event_type") == "interaction.scroll"
    )
    return {
        "interaction.click_count": clicks,
        "interaction.scroll_distance_px": scroll,
        "survey.completion_ratio": survey_completion_ratio,
    }
