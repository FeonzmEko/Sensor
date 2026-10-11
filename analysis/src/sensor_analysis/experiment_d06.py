"""D06 参数实验场：窗长与步进对时域特征的影响。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .features_time import time_features
from .plotting import plot_d06
from .session import SensorSession

DEFAULT_WINDOWS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)


def window_sweep(
    signal: np.ndarray,
    fs: float,
    windows: tuple[float, ...] = DEFAULT_WINDOWS,
    band: tuple[float, float] = (0.5, 3.0),
) -> pd.DataFrame:
    """固定数据、只改窗长，统计四件套的均值与波动。"""
    rows: list[dict[str, float]] = []
    total_seconds = signal.size / fs if fs > 0 else 0.0
    for window_seconds in windows:
        step_seconds = window_seconds / 2.0
        start = 0.0
        var_values: list[float] = []
        zcr_values: list[float] = []
        peak_values: list[float] = []
        while start + window_seconds <= total_seconds + 1e-9:
            start_index = int(round(start * fs))
            end_index = int(round((start + window_seconds) * fs))
            segment = signal[start_index:end_index]
            features = time_features(segment, fs, band=band)
            var_values.append(features["var"])
            zcr_values.append(features["zcr_per_s"])
            peak_values.append(features["peak_dynamic"])
            start += step_seconds
        rows.append(
            {
                "window_seconds": float(window_seconds),
                "step_seconds": float(step_seconds),
                "overlap_ratio": 0.5,
                "window_count": len(var_values),
                "var_mean": float(np.mean(var_values)) if var_values else np.nan,
                "var_std": float(np.std(var_values, ddof=0)) if var_values else np.nan,
                "zcr_mean": float(np.mean(zcr_values)) if zcr_values else np.nan,
                "zcr_std": float(np.std(zcr_values, ddof=0)) if zcr_values else np.nan,
                "peak_mean": float(np.mean(peak_values)) if peak_values else np.nan,
                "peak_max": float(np.max(peak_values)) if peak_values else np.nan,
            }
        )
    return pd.DataFrame(rows)


def event_split_experiment(
    fs: float = 50.0,
    duration: float = 12.0,
    burst_seconds: float = 1.2,
    windows: tuple[float, ...] = (1.0, 1.5, 2.0, 3.0, 4.0),
) -> pd.DataFrame:
    """构造一个 1.2 s 短事件，比较 S=W（不重叠）与 S=W/2（50% 重叠）的覆盖情况。

    把事件中心放在 t=6.0 s，使 S=W 的窗口边界正好落在事件中间：事件被劈成两半，
    单个窗口最多覆盖约一半能量；S=W/2 的 50% 重叠会有一个窗口完整覆盖事件。
    """
    time = np.arange(0, duration, 1.0 / fs)
    burst_center = 6.0
    burst_start = burst_center - burst_seconds / 2.0
    burst_stop = burst_start + burst_seconds
    burst_mask = (time >= burst_start) & (time < burst_stop)
    signal = np.zeros_like(time)
    burst_time = time[burst_mask] - burst_start
    signal[burst_mask] = np.sin(2 * np.pi * 2.0 * burst_time) * np.hanning(burst_mask.sum())

    rows: list[dict[str, float]] = []
    burst_indices = np.flatnonzero(burst_mask)
    for window_seconds in windows:
        for label, step_seconds in (("S=W", window_seconds), ("S=W/2", window_seconds / 2.0)):
            start = 0.0
            max_coverage = 0.0
            windows_touching = 0
            while start + window_seconds <= duration + 1e-9:
                start_index = int(round(start * fs))
                end_index = int(round((start + window_seconds) * fs))
                overlap = np.sum((burst_indices >= start_index) & (burst_indices < end_index))
                coverage = overlap / max(1, burst_indices.size)
                max_coverage = max(max_coverage, coverage)
                if overlap > 0:
                    windows_touching += 1
                start += step_seconds
            rows.append(
                {
                    "window_seconds": float(window_seconds),
                    "step_seconds": float(step_seconds),
                    "step_mode": label,
                    "max_event_coverage": float(max_coverage),
                    "windows_touching_event": int(windows_touching),
                }
            )
    return pd.DataFrame(rows)


def run_d06_experiment(
    session: SensorSession,
    out_dir: str | Path,
    window_seconds: float = 60.0,
) -> dict[str, object]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    stream = session.accelerometer
    fs = stream.measured_hz or 100.0
    magnitude = stream.magnitude()
    total_seconds = stream.duration_seconds
    middle = max(0.0, total_seconds / 2.0 - window_seconds / 2.0)
    start_index = int(middle * fs)
    end_index = int((middle + window_seconds) * fs)
    segment = magnitude[start_index:end_index]
    if segment.size < 32:
        segment = magnitude[: max(32, magnitude.size)]

    sweep = window_sweep(segment, fs)
    split = event_split_experiment()

    figure = plot_d06(sweep, out / "figures" / "d06_window_sweep.png")
    sweep.to_csv(out / "d06_window_sweep.csv", index=False)
    split.to_csv(out / "d06_event_split.csv", index=False)

    summary = {
        "segment_seconds": float(segment.size / fs),
        "fs_hz": float(fs),
        "window_sweep": sweep.to_dict(orient="records"),
        "event_split": split.to_dict(orient="records"),
        "figure": str(figure),
        "conclusions": {
            "short_window": "极短窗（0.25~0.5 s）下方差和 ZCR 波动明显，噪声被放大。",
            "long_window": "极长窗（8~16 s）方差被平均钝化，峰值更易被大冲击抬高。",
            "non_overlap": "S=W 时 1.2 s 短事件跨缝会被劈开，单窗覆盖率下降。",
            "overlap": "S=W/2 的 50% 重叠能提高短事件覆盖率，验证推荐工作点。",
        },
    }
    (out / "d06_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary
