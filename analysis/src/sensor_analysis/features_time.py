"""手写时域四件套：均值、方差、过零率、峰值。

约定：
- 方差采用总体方差（ddof=0），即 sum((x-mean)^2)/N；
- 峰值同时给出原始绝对峰值 peak_raw 与去均值后的动态峰值 peak_dynamic；
- 过零率默认在去均值信号上统计，可选做带限处理（FFT 频带滤波）后再统计；
- zcr_per_s = 过零次数 / 时长（秒），单位为“次/秒”。
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from .session import SensorStream


def bandpass_fft(
    signal: np.ndarray,
    fs: float,
    low_hz: float,
    high_hz: float,
) -> np.ndarray:
    """用 FFT 掩码做零相位带通（派生信号，不修改原始数据）。"""
    if signal.size < 4:
        return signal.copy()
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / fs)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    filtered = np.fft.irfft(spectrum * mask, n=signal.size)
    return filtered


def count_zero_crossings(signal: np.ndarray) -> int:
    centered = signal - float(np.mean(signal))
    if centered.size < 2:
        return 0
    signs = np.sign(centered)
    signs[signs == 0] = 1.0
    return int(np.sum(signs[1:] * signs[:-1] < 0))


def time_features(
    signal: np.ndarray,
    fs: float,
    band: tuple[float, float] | None = None,
) -> dict[str, float]:
    values = np.asarray(signal, dtype=np.float64)
    if values.size == 0:
        return {
            "mean": 0.0,
            "var": 0.0,
            "std": 0.0,
            "rms": 0.0,
            "peak_raw": 0.0,
            "peak_dynamic": 0.0,
            "zero_crossings": 0.0,
            "zcr_per_s": 0.0,
        }

    mean = float(np.mean(values))
    centered = values - mean
    variance = float(np.mean(centered * centered))  # 总体方差 ddof=0
    duration = values.size / fs if fs > 0 else 0.0
    crossings = count_zero_crossings(values)
    bandlimited_crossings = np.nan
    if band is not None and fs > 0:
        filtered = bandpass_fft(values, fs, band[0], band[1])
        bandlimited_crossings = float(count_zero_crossings(filtered))

    return {
        "mean": mean,
        "var": variance,
        "std": float(np.sqrt(max(variance, 0.0))),
        "rms": float(np.sqrt(np.mean(values * values))),
        "peak_raw": float(np.max(np.abs(values))),
        "peak_dynamic": float(np.max(np.abs(centered))),
        "zero_crossings": float(crossings),
        "zcr_per_s": float(crossings / duration) if duration > 0 else 0.0,
        "zero_crossings_bandlimited": bandlimited_crossings,
    }


def window_time_features(
    channels: Mapping[str, np.ndarray],
    fs: float,
    band: tuple[float, float] | None = None,
) -> dict[str, float]:
    features: dict[str, float] = {}
    for name, signal in channels.items():
        for key, value in time_features(signal, fs, band=band).items():
            features[f"{name}_{key}"] = value
    return features


def build_time_feature_table(
    stream: SensorStream,
    windows: pd.DataFrame,
    band: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """为每个窗口计算三轴 + 合矢量的时域四件套。"""
    if windows.empty:
        return windows.copy()

    values = stream.values()
    magnitude = stream.magnitude()
    times = stream.time_seconds
    rows: list[dict[str, float]] = []
    for row in windows.itertuples(index=False):
        start_index = int(row.start_index)
        end_index = int(row.end_index)
        sample_count = max(0, end_index - start_index)
        fs = (sample_count / (row.end_seconds - row.start_seconds)) if row.end_seconds > row.start_seconds else 0.0
        channels = {
            "acc_x": values[start_index:end_index, 0],
            "acc_y": values[start_index:end_index, 1],
            "acc_z": values[start_index:end_index, 2],
            "acc_mag": magnitude[start_index:end_index],
        }
        features = window_time_features(channels, fs, band=band)
        rows.append(
            {
                "session_id": row.session_id,
                "window_id": int(row.window_id),
                "start_seconds": float(row.start_seconds),
                "end_seconds": float(row.end_seconds),
                "start_index": start_index,
                "end_index": end_index,
                "sample_count": sample_count,
                "state": row.state,
                "window_seconds": float(row.window_seconds),
                "step_seconds": float(row.step_seconds),
                "overlap_ratio": float(row.overlap_ratio),
                "fs_hz": float(fs),
                **features,
            }
        )
    return pd.DataFrame(rows)
