"""作业②：公交防误计步的两个可计算特征。

特征 1：步频带能量占比
    R = P(0.5~3 Hz) / P(0.5~10 Hz)
特征 2：峰间隔变异系数
    CV = std(步间隔) / mean(步间隔)

只有当 R 足够高、CV 足够低时，才倾向于判定为步行；单纯“加速度大/方差大”
无法区分步行与车辆振动，本模块用真实步行窗口与车辆振动参考信号验证。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .features_freq import band_energy_ratio, build_frequency_feature_table, peak_interval_statistics
from .plotting import plot_bus_features
from .session import SensorSession
from .windows import WindowSpec, build_windows


def simulate_bus_vibration(
    fs: float = 50.0,
    duration_seconds: float = 120.0,
    seed: int = 20261011,
) -> np.ndarray:
    """构造车辆振动参考信号（仿真），用于验证特征管道。

    真实公交车数据需要第 2 次课 20 分钟路线采集中包含乘车段后替换本信号。
    """
    rng = np.random.default_rng(seed)
    time = np.arange(0.0, duration_seconds, 1.0 / fs)
    signal = (
        0.4 * np.sin(2 * np.pi * 1.1 * time)
        + 0.3 * np.sin(2 * np.pi * 2.2 * time)
        + 3.0 * np.sin(2 * np.pi * 6.5 * time)
        + 2.4 * np.sin(2 * np.pi * 9.0 * time)
        + 1.8 * np.sin(2 * np.pi * 14.0 * time)
        + 9.81
        + rng.normal(0.0, 1.0, time.size)
    )
    return signal


def window_feature_pairs(
    signal: np.ndarray,
    fs: float,
    window_seconds: float = 4.0,
    step_seconds: float = 2.0,
) -> tuple[np.ndarray, np.ndarray]:
    length = int(round(window_seconds * fs))
    step = int(round(step_seconds * fs))
    ratios: list[float] = []
    cvs: list[float] = []
    for start in range(0, max(0, signal.size - length + 1), step):
        segment = signal[start:start + length]
        ratios.append(band_energy_ratio(segment, fs))
        cvs.append(peak_interval_statistics(segment, fs).get("interval_cv", np.nan))
    return np.asarray(ratios, dtype=float), np.asarray(cvs, dtype=float)


def window_variance(
    signal: np.ndarray,
    fs: float,
    window_seconds: float = 4.0,
    step_seconds: float = 2.0,
) -> np.ndarray:
    """只用“方差大不大”做对照基线，用来暴露公交误判问题。"""
    length = int(round(window_seconds * fs))
    step = int(round(step_seconds * fs))
    values: list[float] = []
    for start in range(0, max(0, signal.size - length + 1), step):
        values.append(float(np.var(signal[start:start + length])))
    return np.asarray(values, dtype=float)


def _clean(values: np.ndarray) -> np.ndarray:
    return values[np.isfinite(values)]


def run_bus_experiment(
    session: SensorSession,
    out_dir: str | Path,
    window_seconds: float = 4.0,
    step_seconds: float = 2.0,
    ratio_threshold: float = 0.5,
    cv_threshold: float = 0.35,
) -> dict[str, object]:
    out = Path(out_dir)
    (out / "figures").mkdir(parents=True, exist_ok=True)

    stream = session.accelerometer
    fs = stream.measured_hz or 100.0
    walk_ratio, walk_cv = window_feature_pairs(
        stream.magnitude(), fs, window_seconds, step_seconds
    )
    walk_ratio = _clean(walk_ratio)
    walk_cv = _clean(walk_cv)

    bus_signal = simulate_bus_vibration(fs=fs, duration_seconds=max(60.0, window_seconds * 20))
    bus_ratio, bus_cv = window_feature_pairs(bus_signal, fs, window_seconds, step_seconds)
    bus_ratio = _clean(bus_ratio)
    bus_cv = _clean(bus_cv)

    def classify(ratio: np.ndarray, cv: np.ndarray) -> np.ndarray:
        # CV 缺失时只依赖能量占比，避免把 NaN 直接判成步行。
        cv_value = np.where(np.isfinite(cv), cv, np.inf)
        return (ratio >= ratio_threshold) & (cv_value <= cv_threshold)

    walk_pred = classify(walk_ratio, walk_cv)
    bus_pred = classify(bus_ratio, bus_cv)

    # 对照基线：只用“方差大不大”判定步行。
    walk_var = _clean(window_variance(stream.magnitude(), fs, window_seconds, step_seconds))
    bus_var = _clean(window_variance(bus_signal, fs, window_seconds, step_seconds))
    var_threshold = (
        float((np.median(walk_var) + np.median(bus_var)) / 2.0)
        if walk_var.size and bus_var.size
        else 0.0
    )
    walk_var_pred = walk_var >= var_threshold
    bus_var_pred = bus_var >= var_threshold
    variance_only_false_positive = (
        float(np.mean(bus_var_pred)) if bus_var.size else None
    )

    figure = plot_bus_features(walk_ratio, walk_cv, bus_ratio, bus_cv, out / "figures" / "bus_features.png")

    summary = {
        "window_seconds": window_seconds,
        "step_seconds": step_seconds,
        "fs_hz": float(fs),
        "thresholds": {
            "step_band_energy_ratio": ratio_threshold,
            "peak_interval_cv": cv_threshold,
        },
        "walking": {
            "source": "真实采集的步行数据",
            "window_count": int(walk_ratio.size),
            "ratio_mean": float(np.mean(walk_ratio)) if walk_ratio.size else None,
            "ratio_median": float(np.median(walk_ratio)) if walk_ratio.size else None,
            "cv_mean": float(np.mean(walk_cv)) if walk_cv.size else None,
            "classified_walking_ratio": float(np.mean(walk_pred)) if walk_ratio.size else None,
        },
        "bus": {
            "source": "仿真车辆振动参考信号（真实乘车段待 20 分钟路线采集后替换）",
            "window_count": int(bus_ratio.size),
            "ratio_mean": float(np.mean(bus_ratio)) if bus_ratio.size else None,
            "ratio_median": float(np.median(bus_ratio)) if bus_ratio.size else None,
            "cv_mean": float(np.mean(bus_cv)) if bus_cv.size else None,
            "classified_walking_ratio": float(np.mean(bus_pred)) if bus_ratio.size else None,
        },
        "variance_only_baseline": {
            "threshold_m_s2_squared": var_threshold,
            "walking_classified_walking_ratio": (
                float(np.mean(walk_var_pred)) if walk_var.size else None
            ),
            "bus_classified_walking_ratio": variance_only_false_positive,
            "note": "车辆整体振动会让方差同样很大，只看方差会把大量乘车窗口误判为步行。",
        },
        "figure": str(figure),
        "conclusions": {
            "feature_1": "步频带能量占比 R=P(0.5~3)/P(0.5~10)；步行能量集中在步频带，R 高。",
            "feature_2": "峰间隔变异系数 CV=std/mean；步行节奏稳定，CV 低；车辆振动峰间隔杂乱，CV 高。",
            "why_not_magnitude": "车辆整体振动可能让加速度方差同样很大，仅用“加速度大/方差大”会把乘车误判为步行。",
        },
    }
    (out / "bus_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary
