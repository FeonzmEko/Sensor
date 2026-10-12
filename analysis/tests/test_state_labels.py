"""状态标签归一化与区间解析的单元测试。"""

from __future__ import annotations

import pytest

from sensor_analysis.session import (
    TRANSITION_STATE,
    build_state_intervals,
    make_state_lookup,
    normalize_event_label,
)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("开始步行", ("步行", "start")),
        ("结束步行", ("步行", "end")),
        ("进入电梯", ("电梯", "start")),
        ("离开电梯", ("电梯", "end")),
        ("上楼梯", ("楼梯", "start")),
        ("下楼梯", ("楼梯", "start")),
        ("静止", ("静止", "start")),
        ("开始骑行", ("骑行", "start")),
        (" 开始骑行 ", ("骑行", "start")),
        ("", ("unknown", "start")),
        ("自定义状态", ("自定义状态", "start")),
    ],
)
def test_normalize_event_label(label: str, expected: tuple[str, str]) -> None:
    assert normalize_event_label(label) == expected


def test_build_state_intervals_closes_state_on_end_event() -> None:
    events = [
        (1.0, "上楼梯", "instant"),
        (10.0, "开始步行", "instant"),
        (20.0, "静止", "instant"),
        (25.0, "开始步行", "instant"),
        (40.0, "结束步行", "instant"),
        (45.0, "开始骑行", "instant"),
        (60.0, "结束骑行", "instant"),
    ]
    intervals = build_state_intervals(events, 70.0)

    assert intervals[0] == ("unknown", 0.0, 1.0)
    assert ("楼梯", 1.0, 10.0) in intervals
    assert ("步行", 10.0, 20.0) in intervals
    assert ("静止", 20.0, 25.0) in intervals
    assert ("步行", 25.0, 40.0) in intervals
    assert ("骑行", 45.0, 60.0) in intervals
    # 结束事件之后到下一次进入之前是未标注的过渡段，而不是继续沿用旧状态。
    assert ("过渡", 40.0, 45.0) in intervals
    assert intervals[-1] == (TRANSITION_STATE, 60.0, 70.0)


def test_make_state_lookup_matches_intervals() -> None:
    events = [(10.0, "开始步行", "instant"), (20.0, "结束步行", "instant")]
    lookup = make_state_lookup(events, 30.0)

    assert lookup(0.0) == "unknown"
    assert lookup(5.0) == "unknown"
    assert lookup(15.0) == "步行"
    assert lookup(20.0) == TRANSITION_STATE
    assert lookup(29.0) == TRANSITION_STATE


def test_empty_events_falls_back_to_unknown() -> None:
    assert build_state_intervals([], 10.0) == [("unknown", 0.0, 10.0)]
    assert make_state_lookup([], 10.0)(5.0) == "unknown"
