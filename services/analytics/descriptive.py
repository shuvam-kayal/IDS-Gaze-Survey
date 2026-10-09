"""P4-owned descriptive baseline. No production ML models are implemented yet."""
from statistics import mean, median

def describe(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(values), "mean": mean(values), "median": median(values)}
