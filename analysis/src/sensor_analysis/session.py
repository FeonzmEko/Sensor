"""会话数据读取：CSV + metadata.json + labels.csv。

本模块只负责读取与校验，不改写任何原始文件。原始 CSV 的时间戳、
单位与精度全部按原样保留；所有派生量（相对时间、合矢量、重采样）
都在内存中临时计算。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

ACCELEROMETER_HEADER: tuple[str, ...] = (
    "timestamp_ns",
    "x_m_s2",
    "y_m_s2",
    "z_m_s2",
)
GYROSCOPE_HEADER: tuple[str, ...] = (
    "timestamp_ns",
    "x_rad_s",
    "y_rad_s",
    "z_rad_s",
)
LABELS_HEADER: tuple[str, ...] = (
    "timestamp_elapsed_ns",
    "wall_time_epoch_ms",
    "label",
)

NS_PER_SECOND = 1_000_000_000.0


def _check_header(path: Path, expected: Sequence[str]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first_line = handle.readline().strip()
    header = tuple(part.strip() for part in first_line.split(","))
    if header != tuple(expected):
        raise ValueError(
            f"CSV 表头不符合约定：{path}\n"
            f"  期望：{','.join(expected)}\n"
            f"  实际：{first_line}"
        )


@dataclass
class SensorStream:
    """单个传感器的原始采样序列，附带表头校验信息。"""

    name: str
    unit: str
    frame: pd.DataFrame
    path: Path
    expected_header: tuple[str, ...]
    header_ok: bool = True

    @property
    def timestamp_ns(self) -> np.ndarray:
        return self.frame["timestamp_ns"].to_numpy(dtype=np.int64)

    @property
    def time_seconds(self) -> np.ndarray:
        """相对首样本的时间轴（秒），不用于改写原始 CSV。"""
        timestamps = self.timestamp_ns
        if timestamps.size == 0:
            return np.empty(0, dtype=np.float64)
        return (timestamps - timestamps[0]) / NS_PER_SECOND

    @property
    def axis_columns(self) -> list[str]:
        return [f"{axis}{suffix}" for axis, suffix in zip("xyz", self._axis_suffixes())]

    @property
    def sample_count(self) -> int:
        return int(self.frame.shape[0])

    @property
    def duration_seconds(self) -> float:
        times = self.time_seconds
        return float(times[-1]) if times.size > 1 else 0.0

    @property
    def measured_hz(self) -> float:
        if self.sample_count > 1 and self.duration_seconds > 0:
            return (self.sample_count - 1) / self.duration_seconds
        return 0.0

    def _axis_suffixes(self) -> tuple[str, str, str]:
        columns = [c for c in self.frame.columns if c != "timestamp_ns"]
        if len(columns) != 3:
            raise ValueError(f"{self.name} 需要恰好 3 个数据列，实际为 {columns}")
        # 例如 x_m_s2 -> "_m_s2"，x_rad_s -> "_rad_s"
        suffix = columns[0][1:]
        return (suffix, suffix, suffix)

    def values(self) -> np.ndarray:
        """返回 N×3 的三轴数组（原始单位）。"""
        return self.frame[self.axis_columns].to_numpy(dtype=np.float64)

    def magnitude(self) -> np.ndarray:
        values = self.values()
        return np.sqrt(np.sum(values * values, axis=1))

    def slice_between(self, start_seconds: float, end_seconds: float) -> pd.DataFrame:
        times = self.time_seconds
        mask = (times >= start_seconds) & (times < end_seconds)
        return self.frame.loc[mask]


@dataclass
class SensorSession:
    directory: Path
    metadata: dict
    accelerometer: SensorStream
    gyroscope: SensorStream
    labels: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=LABELS_HEADER))
    labels_path: Path | None = None

    @property
    def session_id(self) -> str:
        return str(self.metadata.get("session_id") or self.directory.name)

    @property
    def duration_seconds(self) -> float:
        return max(self.accelerometer.duration_seconds, self.gyroscope.duration_seconds)

    def stream(self, name: str) -> SensorStream:
        if name in ("accelerometer", "acc", "accel"):
            return self.accelerometer
        if name in ("gyroscope", "gyro"):
            return self.gyroscope
        raise ValueError(f"未知传感器：{name}")

    def label_events(self) -> list[tuple[float, str, str]]:
        """返回 [(相对秒, 标签, 记录类型)]，按时间排序。

        相对时间以加速度计首个样本的 SensorEvent.timestamp 为零点，
        与 SensorStream.time_seconds 使用同一时间轴，便于匹配最近样本。
        """
        if self.labels.empty:
            return []
        timestamps = self.accelerometer.timestamp_ns
        if timestamps.size == 0:
            return []
        first_ns = int(timestamps[0])
        events: list[tuple[float, str, str]] = []
        for row in self.labels.itertuples(index=False):
            elapsed_ns = int(row.timestamp_elapsed_ns)
            events.append(((elapsed_ns - first_ns) / NS_PER_SECOND, str(row.label), "raw_event"))
        return sorted(events, key=lambda item: item[0])


def _load_stream(
    path: Path,
    name: str,
    unit: str,
    expected_header: Sequence[str],
) -> SensorStream:
    if not path.exists():
        raise FileNotFoundError(f"缺少文件：{path}")
    _check_header(path, expected_header)
    frame = pd.read_csv(path)
    if tuple(frame.columns) != tuple(expected_header):
        raise ValueError(f"{path} 读取后的列名与预期不一致：{list(frame.columns)}")
    return SensorStream(
        name=name,
        unit=unit,
        frame=frame,
        path=path,
        expected_header=tuple(expected_header),
    )


def _load_labels(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(LABELS_HEADER))
    _check_header(path, LABELS_HEADER)
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if frame.empty:
        return pd.DataFrame(columns=list(LABELS_HEADER))
    frame["label"] = frame["label"].astype(str).str.strip()
    frame = frame[frame["label"] != ""].reset_index(drop=True)
    return frame


def load_session(directory: str | Path) -> SensorSession:
    """读取一个采集会话目录。"""
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise NotADirectoryError(f"会话目录不存在：{base}")

    metadata_path = base / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"缺少元数据：{metadata_path}")
    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    accelerometer = _load_stream(
        base / "accelerometer.csv",
        name="accelerometer",
        unit="m/s^2",
        expected_header=ACCELEROMETER_HEADER,
    )
    gyroscope = _load_stream(
        base / "gyroscope.csv",
        name="gyroscope",
        unit="rad/s",
        expected_header=GYROSCOPE_HEADER,
    )
    labels_path = base / "labels.csv"
    labels = _load_labels(labels_path)
    return SensorSession(
        directory=base,
        metadata=metadata,
        accelerometer=accelerometer,
        gyroscope=gyroscope,
        labels=labels,
        labels_path=labels_path if labels_path.exists() else None,
    )


def resample_uniform(
    time_seconds: np.ndarray,
    signal: np.ndarray,
    fs: float,
) -> tuple[np.ndarray, np.ndarray]:
    """把非均匀时间戳线性插值到等间隔网格（派生序列，不修改原始数据）。"""
    if time_seconds.size < 2:
        raise ValueError("至少需要 2 个样本才能重采样")
    if fs <= 0:
        raise ValueError(f"采样率必须为正数，实际为 {fs}")
    start = float(time_seconds[0])
    stop = float(time_seconds[-1])
    count = int(np.floor((stop - start) * fs)) + 1
    if count < 2:
        raise ValueError("时长太短，无法按给定 fs 重采样")
    uniform_time = start + np.arange(count) / fs
    uniform_signal = np.interp(uniform_time, time_seconds, signal)
    return uniform_time, uniform_signal


STATE_ALIASES: dict[str, str] = {
    "上楼梯": "楼梯",
    "下楼梯": "楼梯",
    "楼梯": "楼梯",
    "步行": "步行",
    "慢走": "步行",
    "快走": "步行",
    "静止": "静止",
    "电梯": "电梯",
    "骑行": "骑行",
}

TRANSITION_STATE = "过渡"

_START_PREFIXES: tuple[str, ...] = ("开始", "进入")
_END_PREFIXES: tuple[str, ...] = ("结束", "离开")


def normalize_event_label(
    label: str,
    aliases: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """把原始打点标签归一化成 (状态名, 事件类型)。

    事件类型 `kind` 取 `start` / `end`。这样 `开始步行` / `结束步行` 会归一到
    同一个状态 `步行`，而不是被当成两个不同的状态。

    `aliases` 可覆盖默认别名字典，例如把 `上楼梯` / `下楼梯` 保留成两个独立状态。
    """
    table = STATE_ALIASES if aliases is None else aliases
    text = (label or "").strip()
    if not text:
        return "unknown", "start"
    for prefix in _END_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            name = text[len(prefix):]
            return table.get(name, name), "end"
    for prefix in _START_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            name = text[len(prefix):]
            return table.get(name, name), "start"
    return table.get(text, text), "start"


def build_state_intervals(
    events: Iterable[tuple[float, str, str]],
    duration_seconds: float,
    aliases: Mapping[str, str] | None = None,
) -> list[tuple[str, float, float]]:
    """把打点事件转成 (状态, 起始秒, 结束秒) 的非重叠区间序列。

    规则：
    - `开始X` / `进入X` / 裸标签：进入状态 X；
    - `结束X` / `离开X`：若 X 正开放则关闭，之后进入 `过渡`（未标注）直到下一次进入；
    - 第一个事件之前是 `unknown`，最后一个事件之后继承当时的开放状态；
    - 相邻同状态区间合并，零长区间丢弃。
    """
    ordered = sorted(events, key=lambda item: float(item[0]))
    if not ordered:
        # 没有打点标签时，整个会话退化为一个 unknown 区间，保持与原行为一致。
        return [("unknown", 0.0, float(duration_seconds))] if duration_seconds > 0 else []

    changes: list[tuple[float, str]] = []
    current = "unknown"
    for timestamp, label, _kind in ordered:
        state, kind = normalize_event_label(label, aliases)
        moment = float(timestamp)
        if kind == "end":
            if current != state:
                continue
            current = TRANSITION_STATE
        else:
            if current == state:
                continue
            current = state
        changes.append((moment, current))

    if not changes:
        return []

    intervals: list[tuple[str, float, float]] = []
    if changes[0][0] > 0.0:
        intervals.append(("unknown", 0.0, changes[0][0]))
    for index, (start_time, state) in enumerate(changes):
        end_time = changes[index + 1][0] if index + 1 < len(changes) else float(duration_seconds)
        if end_time <= start_time:
            continue
        if intervals and intervals[-1][0] == state and abs(intervals[-1][2] - start_time) < 1e-9:
            intervals[-1] = (state, intervals[-1][1], end_time)
        else:
            intervals.append((state, start_time, end_time))
    return intervals


def make_state_lookup(
    events: Iterable[tuple[float, str, str]],
    duration_seconds: float,
    aliases: Mapping[str, str] | None = None,
) -> Callable[[float], str]:
    """根据事件标签生成 时间 -> 状态 的函数（规则见 `build_state_intervals`）。"""
    intervals = build_state_intervals(events, duration_seconds, aliases)

    def lookup(time_seconds: float) -> str:
        if not intervals:
            return "unknown"
        if time_seconds < intervals[0][1]:
            return "unknown"
        state = "unknown"
        for name, start, end in intervals:
            if start <= time_seconds < end:
                return name
            if time_seconds >= end:
                state = name
        return state

    return lookup
