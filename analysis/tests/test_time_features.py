import numpy as np
import pytest

from sensor_analysis.features_time import (
    bandpass_fft,
    count_zero_crossings,
    time_features,
    window_time_features,
)


def test_mean_and_population_variance():
    signal = np.array([1.0, 2.0, 3.0, 4.0])
    features = time_features(signal, fs=4.0)
    assert features["mean"] == pytest.approx(2.5)
    # 总体方差 ddof=0
    assert features["var"] == pytest.approx(1.25)
    assert features["std"] == pytest.approx(np.sqrt(1.25))


def test_peak_dynamic_removes_dc_offset():
    signal = np.array([10.0, 11.0, 12.0, 11.0])
    features = time_features(signal, fs=4.0)
    assert features["peak_raw"] == pytest.approx(12.0)
    assert features["peak_dynamic"] == pytest.approx(1.0)


def test_zero_crossings_of_cosine():
    fs = 200.0
    frequency = 5.0
    duration = 1.0
    time = np.arange(0.0, duration, 1.0 / fs)
    signal = np.cos(2 * np.pi * frequency * time)
    crossings = count_zero_crossings(signal)
    assert crossings == pytest.approx(2 * frequency * duration, abs=2)


def test_zcr_per_second():
    fs = 100.0
    time = np.arange(0.0, 1.0, 1.0 / fs)
    signal = np.cos(2 * np.pi * 5.0 * time)
    features = time_features(signal, fs=fs)
    assert features["zcr_per_s"] == pytest.approx(10.0, abs=1.0)


def test_bandpass_suppresses_out_of_band_component():
    fs = 100.0
    time = np.arange(0.0, 2.0, 1.0 / fs)
    step = np.sin(2 * np.pi * 1.5 * time)
    noise = np.sin(2 * np.pi * 20.0 * time)
    filtered = bandpass_fft(step + noise, fs, 0.5, 3.0)
    # 带外 20 Hz 分量应被显著压制
    assert np.std(filtered) < np.std(step + noise)
    assert np.std(filtered) == pytest.approx(np.std(step), rel=0.3)


def test_window_time_features_prefixes_channels():
    signal = np.ones(50)
    features = window_time_features({"acc_x": signal, "acc_mag": signal}, fs=50.0)
    assert "acc_x_mean" in features
    assert "acc_mag_var" in features
    assert features["acc_mag_var"] == pytest.approx(0.0)
