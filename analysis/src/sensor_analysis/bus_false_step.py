"""作业②：公交防误计步的两个可计算特征。

特征 1：步频带能量占比
    R = P(0.5~3 Hz) / P(0.5~10 Hz)
特征 2：峰间隔变异系数
    CV = std(步间隔) / mean(步间隔)

只有当 R 足够高、CV 足够低时，才倾向于判定为步行；单纯“加速度大/方差大”
无法区分步行与车辆振动，本模块用真实步行窗口与两类负样本验证：

1. 仿真车辆振动参考信号（发动机 / 路面振动，理想化对照）；
2. 会话中真实打点的非步行状态（默认 `骑行`），用于暴露判据的真实失效边界。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .features_freq import (
    band_energy_ratio,
    build_frequency_feature_table,
    peak_interval_statistics,
)

from .plotting import plot_bus_features, plot_gait_vs_vehicle
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


#: 默认按这些真实状态分组统计两个特征；键是展示名，值是该组的原始状态集合。
DEFAULT_STATE_GROUPS: dict[str, tuple[str, ...]] = {
    "步行": ("步行",),
    "楼梯": ("楼梯",),
    "骑行": ("骑行",),
    "电梯": ("电梯",),
    "静止": ("静止",),
}


def state_group_pairs(
    features: pd.DataFrame,
    states: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray]:
    """从逐窗口特征表里取出某个真实状态分组的 (R, CV)。"""
    if features is None or "state" not in features.columns:
        return np.empty(0), np.empty(0)
    subset = features[features["state"].isin(states)]
    return _clean_pair(
        subset["step_band_energy_ratio"].to_numpy(dtype=float),
        subset["interval_cv"].to_numpy(dtype=float),
    )


def pick_state_window(
    features: pd.DataFrame,
    state: str,
    column: str,
) -> pd.Series | None:
    """挑出某状态下 `column` 最接近中位数的窗口，作为该状态的代表样本。"""
    if features is None or "state" not in features.columns or column not in features.columns:
        return None
    subset = features[features["state"] == state].dropna(subset=[column])
    if subset.empty:
        return None
    target = float(subset[column].median())
    return subset.iloc[int(np.abs(subset[column].to_numpy(dtype=float) - target).argmin())]


def build_gait_vs_vehicle_figure(
    session: SensorSession,
    features: pd.DataFrame | None,
    out_path: str | Path,
    band: tuple[float, float] = (0.5, 3.0),
    gait_state: str = "步行",
    vehicle_state: str = "骑行",
) -> Path | None:
    """步行段与真实骑行段的时域 / 频域并排对照图。"""
    if features is None:
        return None
    gait = pick_state_window(features, gait_state, "acc_mag_var")
    vehicle = pick_state_window(features, vehicle_state, "step_band_energy_ratio")
    if gait is None or vehicle is None:
        return None

    stream = session.accelerometer
    magnitude = stream.magnitude()
    time_axis = stream.time_seconds
    groups: list[tuple[str, np.ndarray, np.ndarray, float]] = []
    for name, row in ((f"{gait_state}（真实打点）", gait), (f"{vehicle_state}（真实打点）", vehicle)):
        start = int(row["start_index"])
        end = int(row["end_index"])
        signal = magnitude[start:end]
        window_seconds = float(row["end_seconds"]) - float(row["start_seconds"])
        fs = signal.size / window_seconds if window_seconds > 0 else 0.0
        groups.append((name, time_axis[start:end] - time_axis[start], signal, fs))
    return plot_gait_vs_vehicle(groups, out_path, band=band)


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


def _clean_pair(ratio: np.ndarray, cv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """成对清洗 R 与 CV，避免分别剔除 NaN 后两个数组长度不一致。"""
    mask = np.isfinite(ratio) & np.isfinite(cv)
    return ratio[mask], cv[mask]


def run_bus_experiment(
    session: SensorSession,
    out_dir: str | Path,
    window_seconds: float = 4.0,
    step_seconds: float = 2.0,
    ratio_threshold: float = 0.5,
    cv_threshold: float = 0.35,
    features: pd.DataFrame | None = None,
    state_groups: dict[str, tuple[str, ...]] | None = None,
    walking_states: tuple[str, ...] = ("步行",),
    vehicle_features: pd.DataFrame | None = None,
    vehicle_label: str = "真实乘车",
    vehicle_source: str = "",
) -> dict[str, object]:
    out = Path(out_dir)
    (out / "figures").mkdir(parents=True, exist_ok=True)

    stream = session.accelerometer
    fs = stream.measured_hz or 100.0

    # 正样本优先取真实打点的步行窗口；没有标签时才退回“整段采集数据”。
    walk_ratio, walk_cv = (
        state_group_pairs(features, walking_states)
        if features is not None
        else (np.empty(0), np.empty(0))
    )
    walk_var = np.empty(0)
    if walk_ratio.size and features is not None:
        walk_var = _clean(
            features.loc[
                features["state"].isin(walking_states), "acc_mag_var"
            ].to_numpy(dtype=float)
        )
        walking_source = "真实打点状态 " + "、".join(walking_states)
        walking_from_labels = True
    else:
        walk_ratio, walk_cv = window_feature_pairs(
            stream.magnitude(), fs, window_seconds, step_seconds
        )
        walk_ratio, walk_cv = _clean_pair(walk_ratio, walk_cv)
        walk_var = _clean(
            window_variance(stream.magnitude(), fs, window_seconds, step_seconds)
        )
        walking_source = "整段采集数据（无打点标签，作为步行近似）"
        walking_from_labels = False

    bus_signal = simulate_bus_vibration(fs=fs, duration_seconds=max(60.0, window_seconds * 20))
    bus_ratio, bus_cv = window_feature_pairs(bus_signal, fs, window_seconds, step_seconds)
    bus_ratio, bus_cv = _clean_pair(bus_ratio, bus_cv)

    def classify(ratio: np.ndarray, cv: np.ndarray) -> np.ndarray:
        # CV 缺失时只依赖能量占比，避免把 NaN 直接判成步行。
        cv_value = np.where(np.isfinite(cv), cv, np.inf)
        return (ratio >= ratio_threshold) & (cv_value <= cv_threshold)

    walk_pred = classify(walk_ratio, walk_cv)
    bus_pred = classify(bus_ratio, bus_cv)

    # 对照基线：只用“方差大不大”判定步行。
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

    plot_extras: list[tuple[str, np.ndarray, np.ndarray]] = []

    # 真实乘车（本实验用真实地铁行驶段）作为首选负样本，替代仿真车辆振动参考。
    real_vehicle: dict[str, object] | None = None
    if vehicle_features is not None and not vehicle_features.empty:
        vehicle_ratio, vehicle_cv = _clean_pair(
            vehicle_features["step_band_energy_ratio"].to_numpy(dtype=float),
            vehicle_features["interval_cv"].to_numpy(dtype=float),
        )
        if vehicle_ratio.size:
            vehicle_pred = classify(vehicle_ratio, vehicle_cv)
            vehicle_var = _clean(
                vehicle_features["acc_mag_var"].to_numpy(dtype=float)
            )
            real_vehicle = {
                "label": vehicle_label,
                "source": vehicle_source,
                "window_count": int(vehicle_ratio.size),
                "ratio_median": float(np.median(vehicle_ratio)),
                "ratio_mean": float(np.mean(vehicle_ratio)),
                "cv_mean": float(np.mean(vehicle_cv)),
                "classified_walking_ratio": float(np.mean(vehicle_pred)),
                "variance_median": float(np.median(vehicle_var)) if vehicle_var.size else None,
                "variance_classified_walking_ratio": (
                    float(np.mean(vehicle_var >= var_threshold))
                    if vehicle_var.size and var_threshold
                    else None
                ),
            }
            plot_extras.append((vehicle_label, vehicle_ratio, vehicle_cv))

    # 真实打点状态的分组统计：骑行等非步行段是这两个特征的真实失效边界。
    real_groups: dict[str, dict[str, object]] = {}
    for name, states in (state_groups or DEFAULT_STATE_GROUPS).items():
        group_ratio, group_cv = state_group_pairs(features, states) if features is not None else (
            np.empty(0),
            np.empty(0),
        )
        if group_ratio.size == 0:
            continue
        group_pred = classify(group_ratio, group_cv)
        group_var = np.empty(0)
        if features is not None and "state" in features.columns:
            group_var = _clean(
                features.loc[features["state"].isin(states), "acc_mag_var"].to_numpy(dtype=float)
            )
        real_groups[name] = {
            "states": list(states),
            "window_count": int(group_ratio.size),
            "ratio_median": float(np.median(group_ratio)),
            "cv_mean": float(np.mean(group_cv)),
            "classified_walking_ratio": float(np.mean(group_pred)),
            "variance_median": float(np.median(group_var)) if group_var.size else None,
            "variance_classified_walking_ratio": (
                float(np.mean(group_var >= var_threshold))
                if group_var.size and var_threshold
                else None
            ),
        }
        plot_extras.append((name, group_ratio, group_cv))

    if walking_from_labels:
        # 正样本已是真实打点状态，避免在图上重复画同一组窗口。
        plot_extras = [item for item in plot_extras if item[0] not in walking_states]

    gait_vehicle_figure = build_gait_vs_vehicle_figure(
        session,
        features,
        out / "figures" / "walk_vs_bike_spectrum.png",
    )

    figure = plot_bus_features(
        walk_ratio,
        walk_cv,
        bus_ratio,
        bus_cv,
        out / "figures" / "bus_features.png",
        extra_groups=tuple(plot_extras),
        walk_label="步行（真实打点状态）" if walking_from_labels else "步行（整段采集）",
    )

    summary = {
        "window_seconds": window_seconds,
        "step_seconds": step_seconds,
        "fs_hz": float(fs),
        "thresholds": {
            "step_band_energy_ratio": ratio_threshold,
            "peak_interval_cv": cv_threshold,
        },
        "walking": {
            "source": walking_source,
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
        "real_vehicle": real_vehicle,
        "real_state_groups": real_groups,
        "gait_vs_vehicle_figure": str(gait_vehicle_figure) if gait_vehicle_figure else None,
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
