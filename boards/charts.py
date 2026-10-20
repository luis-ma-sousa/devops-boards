"""Altair charts with a validated palette that follows the light/dark theme."""

import altair as alt
import pandas as pd
import streamlit as st

from . import config


def _mode() -> str:
    theme = getattr(st.context, "theme", None)
    return "dark" if getattr(theme, "type", None) == "dark" else "light"


def palette() -> list[str]:
    return config.CHART_PALETTE[_mode()]


def _surface() -> str:
    return "#0e1117" if _mode() == "dark" else "#ffffff"


def _muted() -> str:
    return "#8a8984" if _mode() == "dark" else "#7a7974"


# Colour follows the entity: each state always uses the same slot.
def state_scale(states=config.BOARD_COLUMNS):
    pal = palette()
    return alt.Scale(domain=list(states), range=[pal[config.BOARD_COLUMNS.index(s)] for s in states])


def type_scale():
    pal = palette()
    return alt.Scale(domain=config.WORK_ITEM_TYPES, range=pal[: len(config.WORK_ITEM_TYPES)])


def burndown_chart(df: pd.DataFrame, unit: str, height: int = 280):
    pal = palette()
    scale = alt.Scale(domain=["Remaining", "Ideal"], range=[pal[0], _muted()])
    base = alt.Chart(df).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%d/%m", grid=False, tickCount="day")),
        y=alt.Y("value:Q", title=unit, scale=alt.Scale(zero=True)),
        color=alt.Color("series:N", scale=scale, legend=alt.Legend(title=None, orient="top")),
    )
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    remaining = df[df["series"] == "Remaining"]
    lines = base.mark_line(strokeWidth=2).encode(
        strokeDash=alt.condition(alt.datum.series == "Ideal", alt.value([5, 4]), alt.value([1, 0]))
    )
    points = alt.Chart(remaining).mark_point(size=64, filled=True, stroke=_surface(), strokeWidth=2).encode(
        x="date:T", y="value:Q", color=alt.Color("series:N", scale=scale, legend=None),
    )
    wide = df.pivot_table(index="date", columns="series", values="value").reset_index()
    tooltip = [alt.Tooltip("date:T", title="Day", format="%d/%m/%Y")]
    for col in ("Remaining", "Ideal"):
        if col in wide.columns:
            tooltip.append(alt.Tooltip(f"{col}:Q", format=".1f"))
    rule = alt.Chart(wide).mark_rule(color=_muted()).encode(
        x="date:T", opacity=alt.condition(hover, alt.value(0.6), alt.value(0)), tooltip=tooltip,
    ).add_params(hover)
    return (lines + points + rule).properties(height=height)


def velocity_chart(df: pd.DataFrame, height: int = 280):
    pal = palette()
    order = df.drop_duplicates("iteration").sort_values("order")["iteration"].tolist()
    return alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, stroke=_surface(),
                                  strokeWidth=2).encode(
        x=alt.X("iteration:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("points:Q", title="Story Points", stack="zero"),
        color=alt.Color("status:N", scale=alt.Scale(domain=["Completed", "Incomplete"],
                                                   range=[pal[0], pal[1]]),
                        legend=alt.Legend(title=None, orient="top")),
        order=alt.Order("status:N", sort="ascending"),
        tooltip=[alt.Tooltip("iteration:N", title="Iteration"), alt.Tooltip("status:N", title="Status"),
                 alt.Tooltip("points:Q", title="Points", format=".0f")],
    ).properties(height=height)


def cfd_chart(df: pd.DataFrame, height: int = 280):
    stack_order = {"Closed": 0, "Resolved": 1, "Active": 2, "New": 3}
    data = df.assign(stack=df["state"].map(stack_order))
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    area = alt.Chart(data).mark_area(opacity=0.9, stroke=_surface(), strokeWidth=1).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%d/%m", grid=False)),
        y=alt.Y("count:Q", title="Items", stack="zero"),
        color=alt.Color("state:N", scale=state_scale(), legend=alt.Legend(title=None, orient="top")),
        order=alt.Order("stack:Q"),
    )
    wide = df.pivot_table(index="date", columns="state", values="count").reset_index()
    tooltip = [alt.Tooltip("date:T", title="Day", format="%d/%m/%Y")] + [
        alt.Tooltip(f"{s}:Q") for s in reversed(config.BOARD_COLUMNS) if s in wide.columns
    ]
    rule = alt.Chart(wide).mark_rule(color=_muted()).encode(
        x="date:T", opacity=alt.condition(hover, alt.value(0.7), alt.value(0)), tooltip=tooltip,
    ).add_params(hover)
    return (area + rule).properties(height=height)


def stacked_by_state(df: pd.DataFrame, category: str, title: str, height: int = 240):
    """Horizontal bars: count per ``category``, stacked by state."""
    states = [s for s in config.BOARD_COLUMNS if s in set(df["state"])]
    order_map = {s: i for i, s in enumerate(config.BOARD_COLUMNS)}
    data = df.assign(stack=df["state"].map(order_map))
    return alt.Chart(data).mark_bar(cornerRadiusEnd=4, stroke=_surface(), strokeWidth=2).encode(
        y=alt.Y(f"{category}:N", title=None, sort="-x"),
        x=alt.X("count:Q", title=title, stack="zero"),
        color=alt.Color("state:N", scale=state_scale(states), legend=alt.Legend(title=None, orient="top")),
        order=alt.Order("stack:Q"),
        tooltip=[alt.Tooltip(f"{category}:N", title=" "), alt.Tooltip("state:N", title="State"),
                 alt.Tooltip("count:Q", title="Items")],
    ).properties(height=height)


def capacity_chart(df: pd.DataFrame, height: int = 260):
    """Capacity vs. assigned work (hours) per person: side-by-side bars on one axis."""
    pal = palette()
    long = df.melt(id_vars=["name"], value_vars=["Capacity", "Assigned"], var_name="series", value_name="hours")
    return alt.Chart(long).mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y("name:N", title=None),
        yOffset=alt.YOffset("series:N", sort=["Capacity", "Assigned"]),
        x=alt.X("hours:Q", title="Hours"),
        color=alt.Color("series:N", scale=alt.Scale(domain=["Capacity", "Assigned"], range=[pal[0], pal[1]]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("name:N", title="Person"), alt.Tooltip("series:N", title=" "),
                 alt.Tooltip("hours:Q", title="Hours", format=".1f")],
    ).properties(height=height)
