"""滑动窗口与标签区间解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .session import NS_PER_SECOND, SensorSession, SensorStream, make_state_lookup


@dataclass(frozen=True)
class WindowSpec:
    window_seconds: float = 4.0
    step_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds 必须为正数")
        if self.step_seconds <= 0:
            raise ValueError("step_seconds 必须为正数")

    @property
    def overlap_ratio(self) -> float:
        return max(0.0, 1.0 - self.step_seconds / self.window_seconds)

    def describe(self) -> dict[str, float]:
        return {
            "window_seconds": self.window_seconds,
            "step_seconds": self.step_seconds,
            "overlap_ratio": self.overlap_ratio,
        }


def iter_window_bounds(
    duration_seconds: float,
    spec: WindowSpec,
) -> list[tuple[int, float, float]]:
    """返回 [(窗口序号, 起始秒, 结束秒)]，最后一段不足窗长则丢弃。"""
    bounds: list[tuple[int, float, float]] = []
    start = 0.0
    index = 0
    while start + spec.window_seconds <= duration_seconds + 1e-9:
        bounds.append((index, start, start + spec.window_seconds))
        index += 1
        start += spec.step_seconds
    return bounds


def resolve_state_lookup(
    session: SensorSession,
) -> tuple[Callable[[float], str], pd.DataFrame]:
    """生成状态查询函数，并返回 labels_resolved 表。

    输出同时包含：
    - record_type = raw_event：用户实际打点的原始事件；
    - record_type = inferred_interval：按“相邻事件之间继承前一个状态”推断的区间。
    """
    duration = session.duration_seconds
    events = session.label_events()
    lookup = make_state_lookup(events, duration)

    rows: list[dict[str, object]] = []
    for relative_seconds, label, _kind in events:
        rows.append(
            {
                "record_type": "raw_event",
                "state": label,
                "start_seconds": float(relative_seconds),
                "end_seconds": float(relative_seconds),
                "start_elapsed_ns": None,
                "end_elapsed_ns": None,
                "source": "labels.csv",
            }
        )

    boundaries = [0.0] + [t for t, _label, _kind in events if 0.0 <= t <= duration] + [duration]
    boundaries = sorted(set(boundaries))
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        state = lookup((start + end) / 2.0)
        rows.append(
            {
                "record_type": "inferred_interval",
                "state": state,
                "start_seconds": float(start),
                "end_seconds": float(end),
                "start_elapsed_ns": None,
                "end_elapsed_ns": None,
                "source": "inferred_between_events" if state != "unknown" else "unknown",
            }
        )

    frame = pd.DataFrame(
        rows,
        columns=[
            "record_type",
            "state",
            "start_seconds",
            "end_seconds",
            "start_elapsed_ns",
            "end_elapsed_ns",
            "source",
        ],
    )
    if not frame.empty:
        first_ns = int(session.accelerometer.timestamp_ns[0]) if session.accelerometer.sample_count else 0
        mask = frame["record_type"] == "inferred_interval"
        frame.loc[mask, "start_elapsed_ns"] = (
            frame.loc[mask, "start_seconds"] * NS_PER_SECOND + first_ns
        ).astype("int64")
        frame.loc[mask, "end_elapsed_ns"] = (
            frame.loc[mask, "end_seconds"] * NS_PER_SECOND + first_ns
        ).astype("int64")
    return lookup, frame


def build_windows(
    stream: SensorStream,
    spec: WindowSpec,
    session_id: str,
    state_lookup: Callable[[float], str] | None = None,
) -> pd.DataFrame:
    """按时间切窗，返回窗口索引表。"""
    times = stream.time_seconds
    if times.size == 0:
        return pd.DataFrame(
            columns=[
                "session_id",
                "window_id",
                "start_seconds",
                "end_seconds",
                "start_index",
                "end_index",
                "sample_count",
                "state",
                "window_seconds",
                "step_seconds",
                "overlap_ratio",
            ]
        )

    rows: list[dict[str, object]] = []
    for window_id, start, end in iter_window_bounds(stream.duration_seconds, spec):
        start_index = int(np.searchsorted(times, start, side="left"))
        end_index = int(np.searchsorted(times, end, side="left"))
        sample_count = max(0, end_index - start_index)
        state = state_lookup((start + end) / 2.0) if state_lookup else "unknown"
        rows.append(
            {
                "session_id": session_id,
                "window_id": window_id,
                "start_seconds": start,
                "end_seconds": end,
                "start_index": start_index,
                "end_index": end_index,
                "sample_count": sample_count,
                "state": state,
                "window_seconds": spec.window_seconds,
                "step_seconds": spec.step_seconds,
                "overlap_ratio": spec.overlap_ratio,
            }
        )
    return pd.DataFrame(rows)
