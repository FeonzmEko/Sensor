"""FFT 主峰、步频换算与峰间隔法。

约定：
- 单边频谱范围为 0 ~ fs/2；
- 频率分辨率 Δf = fs / N = 1 / W；
- 主峰在行人步频带 0.5 ~ 3 Hz 内查找；
- 步频 step_frequency_spm = f_peak × 60。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from .session import SensorStream, resample_uniform


def detrend(signal: np.ndarray) -> np.ndarray:
    values = np.asarray(signal, dtype=np.float64)
    if values.size == 0:
        return values
    return values - float(np.mean(values))


def single_sided_spectrum(
    signal: np.ndarray,
    fs: float,
    use_hann: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """返回 (freqs, amplitude)，频段 0 ~ fs/2。"""
    values = detrend(signal)
    n = values.size
    if n < 2 or fs <= 0:
        return np.zeros(1), np.zeros(1)
    window = np.hanning(n) if use_hann else np.ones(n)
    coherent_gain = float(np.sum(window)) / n if use_hann else 1.0
    spectrum = np.fft.rfft(values * window)
    amplitude = np.abs(spectrum) * 2.0 / (n * max(coherent_gain, 1e-12))
    amplitude[0] /= 2.0
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    return freqs, amplitude


@dataclass
class DominantPeak:
    frequency_hz: float
    amplitude: float
    resolution_hz: float
    band: tuple[float, float]
    spectrum_freqs: np.ndarray
    spectrum_amplitude: np.ndarray

    @property
    def step_frequency_spm(self) -> float:
        return self.frequency_hz * 60.0


def dominant_frequency(
    signal: np.ndarray,
    fs: float,
    band: tuple[float, float] = (0.5, 3.0),
    use_hann: bool = True,
) -> DominantPeak:
    freqs, amplitude = single_sided_spectrum(signal, fs, use_hann=use_hann)
    resolution = fs / signal.size if signal.size else 0.0
    if freqs.size == 0:
        return DominantPeak(0.0, 0.0, resolution, band, freqs, amplitude)
    mask = (freqs >= band[0]) & (freqs <= band[1])
    if not np.any(mask):
        return DominantPeak(0.0, 0.0, resolution, band, freqs, amplitude)
    band_freqs = freqs[mask]
    band_amplitude = amplitude[mask]
    index = int(np.argmax(band_amplitude))
    return DominantPeak(
        frequency_hz=float(band_freqs[index]),
        amplitude=float(band_amplitude[index]),
        resolution_hz=float(resolution),
        band=band,
        spectrum_freqs=freqs,
        spectrum_amplitude=amplitude,
    )


def band_energy(
    signal: np.ndarray,
    fs: float,
    band: tuple[float, float],
) -> float:
    freqs, amplitude = single_sided_spectrum(signal, fs)
    if freqs.size == 0:
        return 0.0
    mask = (freqs >= band[0]) & (freqs <= band[1])
    return float(np.sum(amplitude[mask] ** 2))


def band_energy_ratio(
    signal: np.ndarray,
    fs: float,
    numerator_band: tuple[float, float] = (0.5, 3.0),
    denominator_band: tuple[float, float] = (0.5, 10.0),
) -> float:
    denominator = band_energy(signal, fs, denominator_band)
    if denominator <= 0:
        return 0.0
    return band_energy(signal, fs, numerator_band) / denominator


def find_peak_intervals(
    signal: np.ndarray,
    fs: float,
    band: tuple[float, float] = (0.5, 3.0),
    min_prominence_ratio: float = 0.25,
) -> np.ndarray:
    """在带通信号上找峰，返回相邻峰间隔（秒）。"""
    values = np.asarray(signal, dtype=np.float64)
    if values.size < 4 or fs <= 0:
        return np.empty(0)
    freqs = np.fft.rfftfreq(values.size, d=1.0 / fs)
    spectrum = np.fft.rfft(detrend(values))
    mask = (freqs >= band[0]) & (freqs <= band[1])
    filtered = np.fft.irfft(spectrum * mask, n=values.size)

    # 最小峰间距取步频带上限对应周期的一半，避免把同一个波峰多次计数。
    min_distance = max(1, int(fs / (band[1] * 2.0)))
    prominence = max(float(np.std(filtered)) * min_prominence_ratio, 1e-9)
    peaks, _ = find_peaks(filtered, distance=min_distance, prominence=prominence)
    if peaks.size < 2:
        return np.empty(0)
    return np.diff(peaks) / fs


def peak_interval_statistics(
    signal: np.ndarray,
    fs: float,
    band: tuple[float, float] = (0.5, 3.0),
) -> dict[str, float]:
    intervals = find_peak_intervals(signal, fs, band=band)
    if intervals.size == 0:
        return {
            "peak_count": 0.0,
            "interval_mean_s": np.nan,
            "interval_std_s": np.nan,
            "interval_cv": np.nan,
            "interval_frequency_hz": np.nan,
        }
    mean = float(np.mean(intervals))
    std = float(np.std(intervals, ddof=0))
    return {
        "peak_count": float(intervals.size + 1),
        "interval_mean_s": mean,
        "interval_std_s": std,
        "interval_cv": std / mean if mean > 0 else np.nan,
        "interval_frequency_hz": 1.0 / mean if mean > 0 else np.nan,
    }


def build_frequency_feature_table(
    stream: SensorStream,
    windows: pd.DataFrame,
    band: tuple[float, float] = (0.5, 3.0),
    denominator_band: tuple[float, float] = (0.5, 10.0),
) -> pd.DataFrame:
    """为每个窗口计算 FFT 主峰、步频、频带能量占比与峰间隔变异系数。"""
    if windows.empty:
        return windows.copy()

    magnitude = stream.magnitude()
    rows: list[dict[str, float]] = []
    for row in windows.itertuples(index=False):
        start_index = int(row.start_index)
        end_index = int(row.end_index)
        window_seconds = float(row.end_seconds) - float(row.start_seconds)
        sample_count = max(0, end_index - start_index)
        fs = sample_count / window_seconds if window_seconds > 0 else 0.0
        segment = magnitude[start_index:end_index]
        if segment.size >= 4 and fs > 0:
            peak = dominant_frequency(segment, fs, band=band)
            ratio = band_energy_ratio(segment, fs, band, denominator_band)
            interval = peak_interval_statistics(segment, fs, band=band)
        else:
            peak = None
            ratio = np.nan
            interval = {
                "peak_count": 0.0,
                "interval_mean_s": np.nan,
                "interval_std_s": np.nan,
                "interval_cv": np.nan,
                "interval_frequency_hz": np.nan,
            }
        rows.append(
            {
                "session_id": row.session_id,
                "window_id": int(row.window_id),
                "start_seconds": float(row.start_seconds),
                "end_seconds": float(row.end_seconds),
                "state": row.state,
                "fs_hz": float(fs),
                "f_peak_hz": peak.frequency_hz if peak else np.nan,
                "f_peak_amplitude": peak.amplitude if peak else np.nan,
                "frequency_resolution_hz": peak.resolution_hz if peak else np.nan,
                "step_frequency_spm": peak.step_frequency_spm if peak else np.nan,
                "step_band_energy_ratio": ratio,
                **interval,
            }
        )
    return pd.DataFrame(rows)


def spectrum_for_window(
    signal: np.ndarray,
    fs: float,
    band: tuple[float, float] = (0.5, 3.0),
) -> dict[str, np.ndarray | float]:
    peak = dominant_frequency(signal, fs, band=band)
    return {
        "freqs": peak.spectrum_freqs,
        "amplitude": peak.spectrum_amplitude,
        "f_peak_hz": peak.frequency_hz,
        "step_frequency_spm": peak.step_frequency_spm,
        "resolution_hz": peak.resolution_hz,
    }


def uniform_spectrum(
    time_seconds: np.ndarray,
    signal: np.ndarray,
    target_fs: float,
    band: tuple[float, float] = (0.5, 3.0),
) -> dict[str, np.ndarray | float]:
    """先把非均匀采样重采样到等间隔网格，再计算频谱。"""
    uniform_time, uniform_signal = resample_uniform(time_seconds, signal, target_fs)
    peak = dominant_frequency(uniform_signal, target_fs, band=band)
    return {
        "uniform_time": uniform_time,
        "uniform_signal": uniform_signal,
        "freqs": peak.spectrum_freqs,
        "amplitude": peak.spectrum_amplitude,
        "f_peak_hz": peak.frequency_hz,
        "step_frequency_spm": peak.step_frequency_spm,
        "resolution_hz": peak.resolution_hz,
    }
