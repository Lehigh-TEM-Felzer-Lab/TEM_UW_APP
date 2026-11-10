# time_units.py
"""Times in seconds, as TEM_2026 converts them (tem_core/tem_time.h): units, run length and the model step.

20261110 Created: run_dt and run_length in any unit (second, minute, hour, day, week, month, year) are converted
         to seconds on the 365-day noleap year; the app stages monthly or daily forcing, so it accepts a step of
         one calendar month or one day written in any unit (1 day, 24 hours, 86400 seconds).
"""

SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 7 * 86400,
    "month": 365 * 86400 // 12,  # the mean month
    "year": 365 * 86400,
}
ALIASES = {
    "s": "second",
    "sec": "second",
    "secs": "second",
    "min": "minute",
    "mins": "minute",
    "h": "hour",
    "hr": "hour",
    "hrs": "hour",
    "d": "day",
    "yr": "year",
    "yrs": "year",
}
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
YEAR_SECONDS = SECONDS["year"]


def unit_name(units) -> str:
    """Singular unit name of a spelling such as seconds, sec, hr or days."""
    u = str(units).strip().lower()
    u = ALIASES.get(u, u)
    if u.endswith("s") and u[:-1] in SECONDS:
        u = u[:-1]
    if u not in SECONDS:
        raise ValueError(
            f"unit {units!r} is not one of second, minute, hour, day, week, month, year"
        )
    return u


def to_seconds(n, units) -> int:
    """Seconds in n units; a month is the mean month (use run_seconds for calendar months)."""
    return int(n) * SECONDS[unit_name(units)]


def run_seconds(n, units) -> int:
    """Seconds in a run of n units from 1 January: months are the calendar months of the noleap year."""
    if unit_name(units) == "month":
        return YEAR_SECONDS * (n // 12) + 86400 * sum(MONTH_DAYS[: n % 12])
    return to_seconds(n, units)


def step_kind(run_dt, run_dt_units) -> str:
    """'month' or 'day' for a step of one calendar month or one day; other steps are not staged by the app."""
    if unit_name(run_dt_units) == "month" and run_dt == 1:
        return "month"
    if to_seconds(run_dt, run_dt_units) == 86400:
        return "day"
    raise ValueError(
        "the app stages forcing for a step of one month or one day (1 month, 1 day, 24 hours or 86400 seconds); "
        f"run_dt {run_dt} {run_dt_units} is {to_seconds(run_dt, run_dt_units)} s"
    )


def run_steps(n, units, kind):
    """Steps in a run of n units from 1 January, or None when it is not a whole number of steps."""
    total = run_seconds(n, units)
    if kind == "day":
        return total // 86400 if total % 86400 == 0 else None
    steps = elapsed = 0
    while elapsed < total:
        elapsed += 86400 * MONTH_DAYS[steps % 12]
        steps += 1
    return steps if elapsed == total else None
