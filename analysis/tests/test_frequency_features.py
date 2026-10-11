import numpy as np
import pytest

from sensor_analysis.experiment_d07 import fold_frequency
from sensor_analysis.features_freq import (
    band_energy_ratio,
    dominant_frequency,
    peak_interval_statistics,
    single_sided_spectrum,
)


def _sine(frequency: float, fs: float, duration: float) -> np.ndarray:
    time = np.arange(0.0, duration, 1.0 / fs)
    return np.sin(2 * np.pi * frequency * time)


def test_single_sided_spectrum_peak_bin():
    fs = 50.0
    duration = 10.0
    signal = _sine(1.2, fs, duration)
    freqs, amplitude = single_sided_spectrum(signal, fs)
    peak_index = int(np.argmax(amplitude))
    assert freqs[peak_index] == pytest.approx(1.2, abs=0.1)


def test_dominant_frequency_and_step_conversion():
    fs = 50.0
    signal = _sine(1.2, fs, 10.0)
    peak = dominant_frequency(signal, fs, band=(0.5, 3.0))
    assert peak.frequency_hz == pytest.approx(1.2, abs=0.1)
    assert peak.step_frequency_spm == pytest.approx(72.0, abs=6.0)


def test_band_energy_ratio_prefers_step_band():
    fs = 50.0
    step_signal = _sine(1.5, fs, 10.0)
    vibration_signal = _sine(8.0, fs, 10.0)
    step_ratio = band_energy_ratio(step_signal, fs)
    vibration_ratio = band_energy_ratio(vibration_signal, fs)
    assert step_ratio > vibration_ratio
    assert step_ratio == pytest.approx(1.0, abs=0.05)


def test_peak_interval_statistics_regular_signal():
    fs = 100.0
    signal = _sine(1.0, fs, 20.0)
    stats = peak_interval_statistics(signal, fs)
    assert stats["interval_mean_s"] == pytest.approx(1.0, abs=0.05)
    assert stats["interval_cv"] == pytest.approx(0.0, abs=0.05)


def test_fold_frequency_28hz_at_2hz():
    # 标准奈奎斯特折叠为 0.8 Hz；课程页面的 1.2 Hz 是它关于 fs 的镜像。
    assert fold_frequency(2.8, 2.0) == pytest.approx(0.8, abs=1e-9)
    assert fold_frequency(2.8, 3.0) == pytest.approx(0.2, abs=1e-9)
    assert fold_frequency(2.8, 5.0) == pytest.approx(2.2, abs=1e-9)
    assert fold_frequency(2.8, 50.0) == pytest.approx(2.8, abs=1e-9)
