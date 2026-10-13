"""多会话合并、跨会话切分校验与双口径指标的单元测试。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sensor_analysis import advanced as adv
from sensor_analysis.session import ACCELEROMETER_HEADER, GYROSCOPE_HEADER, SensorSession, SensorStream
from sensor_analysis.windows import WindowSpec


def _stream(session_id: str, name: str, unit: str, header, duration: float, hz: float) -> SensorStream:
    count = int(duration * hz) + 1
    timestamps = (np.arange(count) * (1_000_000_000 / hz)).astype(np.int64)
    frame = pd.DataFrame(
        {
            "timestamp_ns": timestamps,
            header[1]: np.zeros(count),
            header[2]: np.zeros(count),
            header[3]: np.full(count, 9.81),
        }
    )
    return SensorStream(
        name=name,
        unit=unit,
        frame=frame,
        path=Path(session_id) / f"{name}.csv",
        expected_header=tuple(header),
    )


def _session(session_id: str, label: str, duration: float = 60.0, hz: float = 50.0) -> SensorSession:
    accel = _stream(session_id, "accelerometer", "m/s^2", ACCELEROMETER_HEADER, duration, hz)
    gyro = _stream(session_id, "gyroscope", "rad/s", GYROSCOPE_HEADER, duration, hz)
    labels = pd.DataFrame(
        {"timestamp_elapsed_ns": [0], "wall_time_epoch_ms": [0], "label": [label]}
    )
    return SensorSession(
        directory=Path(session_id),
        metadata={"session_id": session_id},
        accelerometer=accel,
        gyroscope=gyro,
        labels=labels,
    )


def test_multi_session_window_ids_and_segments_do_not_collide():
    spec = WindowSpec(window_seconds=4.0, step_seconds=2.0)
    first = _session("SESS-A", "静止")
    second = _session("SESS-B", "开始步行")

    part_a = adv.build_pure_windows(
        first, spec, session_key="S1", window_offset=0, prefix_segments=True
    )
    part_b = adv.build_pure_windows(
        second, spec, session_key="S2", window_offset=adv.SESSION_WINDOW_OFFSET, prefix_segments=True
    )

    assert set(part_a["window_id"]) & set(part_b["window_id"]) == set()
    assert part_a["window_id"].max() < part_b["window_id"].min()
    assert set(part_a["segment_id"]) & set(part_b["segment_id"]) == set()
    assert part_a["segment_id"].iloc[0].startswith("S1-")
    assert part_b["segment_id"].iloc[0].startswith("S2-")
    assert set(part_a["session_id"]) == {"SESS-A"}
    assert set(part_b["session_id"]) == {"SESS-B"}


def test_single_session_keeps_legacy_window_ids_and_segment_names():
    spec = WindowSpec(window_seconds=4.0, step_seconds=2.0)
    part = adv.build_pure_windows(_session("SESS-A", "静止"), spec)
    assert part["window_id"].iloc[0] == 0
    assert part["segment_id"].iloc[0] == "静止-00"


def test_check_no_overlap_ignores_cross_session_time_ranges():
    spec = WindowSpec(window_seconds=4.0, step_seconds=2.0)
    part_a = adv.build_pure_windows(
        _session("SESS-A", "静止"), spec, session_key="S1", window_offset=0, prefix_segments=True
    )
    part_b = adv.build_pure_windows(
        _session("SESS-B", "开始步行"),
        spec,
        session_key="S2",
        window_offset=adv.SESSION_WINDOW_OFFSET,
        prefix_segments=True,
    )
    meta = pd.concat([part_a, part_b], ignore_index=True)

    cross = adv.check_no_overlap(meta, part_a["window_id"].to_numpy(), part_b["window_id"].to_numpy())
    assert cross["passed"] is True
    assert cross["sessions_checked"] == 2

    same = adv.check_no_overlap(
        meta,
        part_a["window_id"].to_numpy()[:5],
        part_a["window_id"].to_numpy()[:5],
    )
    assert same["passed"] is False
    assert same["overlapping_window_pairs"] > 0


def test_train_xgboost_reports_stable_macro_f1_with_two_viewpoints():
    pytest.importorskip("xgboost")
    rng = np.random.default_rng(7)
    # 3 类各 20 个窗口；验证集里 C 只有 1 个窗口，应被稳定口径剔除。
    features = pd.DataFrame(
        {
            "f0": rng.normal(size=60),
            "f1": rng.normal(size=60),
            "f2": rng.normal(size=60),
        }
    )
    labels = np.array(["A"] * 20 + ["B"] * 20 + ["C"] * 20)
    train_rows = list(range(0, 14)) + list(range(20, 34)) + list(range(40, 59))
    test_rows = list(range(14, 20)) + list(range(34, 40)) + [59]
    y, classes = adv._label_encode(pd.Series(labels))
    y = pd.Series(y)

    _, metrics, _ = adv.train_xgboost(
        features.loc[train_rows],
        y.loc[train_rows].to_numpy(),
        features.loc[test_rows],
        y.loc[test_rows].to_numpy(),
        classes,
        n_estimators=30,
        min_test_support=5,
    )
    assert classes == ["A", "B", "C"]
    assert metrics["stable_classes"] == ["A", "B"]
    assert metrics["classes_below_min_support"] == ["C"]
    assert metrics["macro_f1_stable"] != metrics["macro_f1"]
