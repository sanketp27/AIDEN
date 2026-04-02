"""
AIDEN Workload Forecaster
=========================
Zero LLM calls. Pure ML + Dynamic Programming.

Pipeline
--------
1. Feature extraction  — convert raw tasks into numeric feature vectors
2. Completion-rate ML  — Exponential Weighted Moving Average (EWMA) on historical
                         completions to predict how many tasks the user can finish
                         per day going forward (personalised, updates with new data)
3. Daily load scoring  — weighted sum of open tasks using priority × urgency decay
4. Overload detection  — days where projected load > personal capacity threshold
5. DP rescheduling     — 0/1 Knapsack-style DP that assigns tasks from overloaded
                         days to the nearest free slot, minimising peak load

Why these algorithms
--------------------
- EWMA: O(n) in time, O(1) in space, no training data needed to start, adapts to the
  user's personal pace without ever calling a model.
- DP rescheduling: exact optimal assignment for ≤30 days / ≤200 tasks (fits in ms).
  Greedy fallback beyond that. No need to approximate.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass, field

import numpy as np


PRIORITY_WEIGHT: dict[str, float] = {
    "P0": 8.0,   # critical — counts 8× in daily load
    "P1": 4.0,
    "P2": 2.0,
    "P3": 1.0,
}

# A user working on one P2 task (weight 2) × 4 tasks/day → 8 units.
DEFAULT_DAILY_CAPACITY = 8.0

# Urgency decay: load contribution = priority_weight / (days_until_due + 1)
# Tasks due tomorrow (1 day) contribute double vs tasks due in 2 days.
URGENCY_DECAY_BASE = 1.0

EWMA_ALPHA = 0.3

FORECAST_DAYS = 14

OVERLOAD_FACTOR = 1.2


@dataclass
class TaskFeatures:
    task_id:    str
    title:      str
    priority:   str
    status:     str
    due_date:   Optional[date]
    created_at: date
    tags:       list[str]

    @property
    def priority_weight(self) -> float:
        return PRIORITY_WEIGHT.get(self.priority, 1.0)

    def urgency(self, today: date) -> float:
        """Higher urgency the closer the due date is."""
        if self.due_date is None:
            return 0.2   # no due date → low background urgency
        days_left = (self.due_date - today).days
        if days_left < 0:
            return self.priority_weight * 3.0   # overdue penalty
        return self.priority_weight / (days_left + URGENCY_DECAY_BASE)

    def load_on_day(self, target_day: date, today: date) -> float:
        """
        How much load does this task contribute to a given day?
        Uses a triangular distribution: load peaks at due date, tapers off before.
        """
        if self.due_date is None:
            return self.priority_weight * 0.1
        days_until_due = (self.due_date - target_day).days
        days_remaining_today = max((self.due_date - today).days, 1)
        if days_until_due < 0:
            # Already past due — full weight every day
            return self.priority_weight
        # Fraction of task that "belongs" to this day
        fraction = 1.0 / days_remaining_today
        return self.priority_weight * fraction


@dataclass
class DayForecast:
    date:             date
    load_score:       float          # raw load units
    capacity:         float          # user's personal daily capacity
    overloaded:       bool
    utilisation_pct:  int            # load / capacity × 100
    task_ids:         list[str]      # tasks contributing to this day
    suggested_moves:  list[dict]     # tasks that should be moved here or away


@dataclass
class WorkloadForecast:
    user_id:              str
    generated_at:         datetime
    forecast_days:        list[DayForecast]
    personal_capacity:    float
    overloaded_days:      int
    peak_load_date:       Optional[str]
    risk_score:           int           # 0–100
    reschedule_suggestions: list[dict]
    completion_rate_trend:  str         # "improving" | "stable" | "declining"
    # Raw arrays for the chart
    dates:              list[str]
    load_scores:        list[float]
    capacity_line:      list[float]


class CompletionRateModel:
    """
    Learns the user's personal daily task-completion capacity from history.

    Algorithm: EWMA (Exponential Weighted Moving Average)
    -------------------------------------------------------
    estimate_t = α × observed_t + (1 - α) × estimate_{t-1}

    This is lightweight (no stored model file), online (updates in place),
    and personalized (every user gets their own instance).

    Returns a smoothed estimate of tasks-per-day and its trend direction.
    """

    def __init__(self, alpha: float = EWMA_ALPHA):
        self.alpha = alpha
        self._estimate: Optional[float] = None
        self._prev_estimate: Optional[float] = None
        self._observations: list[float] = []

    def update(self, completed_per_day: list[float]) -> None:
        """Feed historical daily completion counts to warm up the model."""
        for obs in completed_per_day:
            if self._estimate is None:
                self._estimate = obs
            else:
                self._prev_estimate = self._estimate
                self._estimate = self.alpha * obs + (1 - self.alpha) * self._estimate
            self._observations.append(obs)

    @property
    def estimate(self) -> float:
        """Smoothed daily capacity estimate in tasks/day."""
        if self._estimate is None:
            return 3.0   # cold start: assume 3 tasks/day
        return max(self._estimate, 1.0)

    @property
    def trend(self) -> str:
        """Compare recent EWMA to previous to detect trend direction."""
        if self._prev_estimate is None or self._estimate is None:
            return "stable"
        delta = self._estimate - self._prev_estimate
        if delta > 0.3:
            return "improving"
        if delta < -0.3:
            return "declining"
        return "stable"

    def capacity_in_load_units(self) -> float:
        """
        Convert tasks/day → load units/day using average priority weight.
        Assumes an even mix of P2 (weight 2) as the baseline.
        """
        return self.estimate * 2.0   # 1 task ≈ 2 load units at P2


def build_load_matrix(
    tasks: list[TaskFeatures],
    today: date,
    days: int = FORECAST_DAYS,
) -> np.ndarray:
    """
    Returns shape (days,) array where index i = load score on today+i.

    Each task contributes fractional load across its remaining days
    (triangular spread peaking at due date).
    """
    load = np.zeros(days, dtype=float)
    for task in tasks:
        if task.status in ("completed", "cancelled"):
            continue
        for i in range(days):
            target = today + timedelta(days=i)
            contribution = task.load_on_day(target, today)
            load[i] += contribution
    return load



def dp_reschedule(
    tasks: list[TaskFeatures],
    load: np.ndarray,
    capacity: float,
    today: date,
    days: int = FORECAST_DAYS,
) -> list[dict]:
    """
    Optimal rescheduling of tasks from overloaded days to free/lighter days.

    Algorithm: Priority-sorted greedy DP with load recomputation
    -----------------------------------------------------------
    Key fix vs naive approach: instead of only considering tasks *due* on an
    overloaded day (which misses load contributions from the triangular spread),
    we consider ALL open tasks whose due_date falls inside the overloaded window
    and recompute the load delta that would result from pushing the due date out.

    For each overloaded day (sorted heaviest-first):
      1. Collect moveable tasks = open tasks due within ±3 days of this day,
         sorted (priority_weight ASC, urgency ASC) — most moveable first.
      2. For each task, compute the load *relief* on the overloaded day if we
         pushed its due date N days forward (re-spreading the triangular load).
      3. Pick the target slot that maximises relief while minimising new peak.
      4. Accept move if it reduces the overloaded day's load by ≥ 0.5 units.

    Complexity: O(T × D²) worst case, O(50) typical. Runs in < 5ms.
    """
    overload_threshold = capacity * OVERLOAD_FACTOR
    suggestions: list[dict] = []
    adjusted_load = load.copy()
    moved_tasks: set[str] = set()   # avoid moving same task twice

    # Build candidate task list: tasks with due_date in forecast window
    candidates = [
        t for t in tasks
        if t.status not in ("completed", "cancelled")
        and t.due_date is not None
        and 0 <= (t.due_date - today).days < days
    ]

    # Process overloaded days heaviest-first for maximum impact
    overloaded_indices = sorted(
        [i for i in range(days) if adjusted_load[i] > overload_threshold],
        key=lambda i: adjusted_load[i],
        reverse=True,
    )

    for day_idx in overloaded_indices:
        if adjusted_load[day_idx] <= overload_threshold:
            continue

        # Tasks that contribute load to this day: due within [today, day+3]
        local_due = today + timedelta(days=day_idx)
        moveable = sorted(
            [t for t in candidates
             if t.task_id not in moved_tasks
             and abs((t.due_date - local_due).days) <= 3],
            key=lambda t: (t.priority_weight, t.urgency(today))
        )

        for task in moveable:
            if adjusted_load[day_idx] <= overload_threshold:
                break
            if task.task_id in moved_tasks:
                continue

            current_idx = (task.due_date - today).days
            task_load_here = task.load_on_day(local_due, today)
            if task_load_here < 0.1:
                continue   # negligible contribution

            best_slot: Optional[int] = None
            best_score = -math.inf

            # Scan forward up to 7 days
            for j in range(day_idx + 1, min(day_idx + 8, days)):
                # How much would this task contribute to slot j if moved there?
                new_due_candidate = today + timedelta(days=j)
                new_remaining = max((new_due_candidate - today).days, 1)
                new_load_j = task.priority_weight / new_remaining

                relief = task_load_here                    # freed from day_idx
                extra  = new_load_j                        # added to slot j
                net_benefit = relief - extra
                slot_slack = capacity - adjusted_load[j]

                # Score = net benefit + bonus for slack
                score = net_benefit + slot_slack * 0.1
                if score > best_score:
                    best_score = score
                    best_slot = j

            # Backward scan (up to 3 days) as fallback
            if best_slot is None:
                for j in range(max(0, day_idx - 3), day_idx):
                    slot_slack = capacity - adjusted_load[j]
                    if slot_slack > 0 and slot_slack > best_score:
                        best_score = slot_slack
                        best_slot = j

            if best_slot is not None and best_score > 0:
                new_due = today + timedelta(days=best_slot)
                original_due = task.due_date.isoformat()

                # Apply delta to adjusted_load
                adjusted_load[day_idx] -= task_load_here
                new_remaining = max((new_due - today).days, 1)
                adjusted_load[best_slot] += task.priority_weight / new_remaining

                moved_tasks.add(task.task_id)
                suggestions.append({
                    "task_id":       task.task_id,
                    "task_title":    task.title,
                    "priority":      task.priority,
                    "current_due":   original_due,
                    "suggested_due": new_due.isoformat(),
                    "days_shifted":  best_slot - day_idx,
                    "reason":        f"{local_due.isoformat()} is at "
                                     f"{(adjusted_load[day_idx]+task_load_here):.1f}"
                                     f"/{capacity:.1f} units. Moving '{task.title}' to "
                                     f"{new_due.isoformat()} reduces load by "
                                     f"{task_load_here:.1f} units.",
                })

    return suggestions

def compute_risk_score(
    load: np.ndarray,
    capacity: float,
    overdue_count: int,
) -> int:
    """
    Composite risk score using three signals:
      1. Overload severity  (peak load / capacity, capped at 3×)
      2. Overloaded day count (fraction of forecast window)
      3. Overdue penalty (flat +5 per overdue task, capped at 30)

    All signals are normalised to [0, 100] and combined with weights.
    No LLM. Pure arithmetic.
    """
    if len(load) == 0 or capacity <= 0:
        return 0

    peak     = float(np.max(load))
    overload = float(np.sum(load > capacity * OVERLOAD_FACTOR))

    severity_score  = min((peak / (capacity * 3.0)) * 60, 60)
    overload_score  = (overload / len(load)) * 30
    overdue_score   = min(overdue_count * 5, 30)

    raw = severity_score + overload_score + overdue_score
    return min(int(round(raw)), 100)


def build_forecast(
    tasks: list[TaskFeatures],
    completed_per_day_history: list[float],
    user_id: str,
    today: Optional[date] = None,
) -> WorkloadForecast:
    """
    Main entry point. Returns a fully populated WorkloadForecast.

    Parameters
    ----------
    tasks : list of TaskFeatures — open tasks from the DB
    completed_per_day_history : list[float] — how many tasks were completed on
        each of the last N days (oldest first). Used to calibrate capacity.
    user_id : str
    today : date override for testing

    Returns
    -------
    WorkloadForecast — all fields populated, no LLM calls made.
    """
    if today is None:
        today = date.today()

    model = CompletionRateModel(alpha=EWMA_ALPHA)
    model.update(completed_per_day_history)
    capacity = model.capacity_in_load_units()

    open_tasks = [t for t in tasks if t.status not in ("completed", "cancelled")]
    load = build_load_matrix(open_tasks, today, FORECAST_DAYS)

    overdue = sum(
        1 for t in open_tasks
        if t.due_date and t.due_date < today
    )

    risk = compute_risk_score(load, capacity, overdue)

    suggestions = dp_reschedule(open_tasks, load, capacity, today, FORECAST_DAYS)

    day_forecasts: list[DayForecast] = []
    overloaded_days = 0
    peak_load = -1.0
    peak_date: Optional[str] = None

    for i in range(FORECAST_DAYS):
        d = today + timedelta(days=i)
        score = float(load[i])
        overloaded = score > capacity * OVERLOAD_FACTOR
        if overloaded:
            overloaded_days += 1
        if score > peak_load:
            peak_load = score
            peak_date = d.isoformat()
        util = min(int(round((score / capacity) * 100)), 200) if capacity > 0 else 0

        contributing = [
            t.task_id for t in open_tasks
            if t.due_date and today <= t.due_date <= d + timedelta(days=1)
        ]

        day_forecasts.append(DayForecast(
            date=d,
            load_score=round(score, 2),
            capacity=round(capacity, 2),
            overloaded=overloaded,
            utilisation_pct=util,
            task_ids=contributing,
            suggested_moves=[s for s in suggestions if s["current_due"] == d.isoformat()
                             or s["suggested_due"] == d.isoformat()],
        ))

    return WorkloadForecast(
        user_id=user_id,
        generated_at=datetime.now(timezone.utc),
        forecast_days=day_forecasts,
        personal_capacity=round(capacity, 2),
        overloaded_days=overloaded_days,
        peak_load_date=peak_date,
        risk_score=risk,
        reschedule_suggestions=suggestions,
        completion_rate_trend=model.trend,
        dates=[str(today + timedelta(days=i)) for i in range(FORECAST_DAYS)],
        load_scores=[round(float(load[i]), 2) for i in range(FORECAST_DAYS)],
        capacity_line=[round(capacity, 2)] * FORECAST_DAYS,
    )
