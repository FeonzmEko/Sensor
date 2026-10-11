from pathlib import Path

import numpy as np
import pandas as pd

from sensor_analysis.bus_false_step import run_bus_experiment, window_feature_pairs
from sensor_analysis.session import SensorSession, SensorStream


def _synthetic_session(fs: float = 50.0, duration_seconds: float = 20.0) -> SensorSession:
    time = np.arange(0.0, duration_seconds, 1.0 / fs)
    acc = 9.81 + np.sin(2 * np.pi * 1.8 * time)
    gyro = 0.05 * np.sin(2 * np.pi * 1.8 * time)
    frame = pd.DataFrame(
        {
            "timestamp_ns": (time * 1e9).astype("int64"),
            "x_m_s2": acc,
            "y_m_s2": acc * 0.1,
            "z_m_s2": acc * 0.2,
        }
    )
    gyro_frame = pd.DataFrame(
        {
            "timestamp_ns": (time * 1e9).astype("int64"),
            "x_rad_s": gyro,
            "y_rad_s": gyro,
            "z_rad_s": gyro,
        }
    )
    stream = SensorStream(
        name="accelerometer",
        unit="m/s^2",
        frame=frame,
        path=Path("/tmp/synthetic/accelerometer.csv"),
        expected_header=("timestamp_ns", "x_m_s2", "y_m_s2", "z_m_s2"),
    )
    gyro_stream = SensorStream(
        name="gyroscope",
        unit="rad/s",
        frame=gyro_frame,
        path=Path("/tmp/synthetic/gyroscope.csv"),
        expected_header=("timestamp_ns", "x_rad_s", "y_rad_s", "z_rad_s"),
    )
    return SensorSession(
        directory=Path("/tmp/synthetic"),
        metadata={"session_id": "synthetic"},
        accelerometer=stream,
        gyroscope=gyro_stream,
    )


def test_window_feature_pairs_are_paired():
    rng = np.random.default_rng(7)
    signal = 9.81 + np.sin(2 * np.pi * 1.5 * np.arange(0, 10 * 50) / 50) + rng.normal(0, 0.1, 500)
    ratios, cvs = window_feature_pairs(signal, 50.0, window_seconds=2.0, step_seconds=1.0)
    assert ratios.shape == cvs.shape


def test_bus_experiment_handles_short_windows(tmp_path):
    session = _synthetic_session()
    summary = run_bus_experiment(session, tmp_path, window_seconds=2.0, step_seconds=1.0)
    assert summary["walking"]["window_count"] > 0
    assert summary["bus"]["window_count"] > 0
    assert summary["variance_only_baseline"]["threshold_m_s2_squared"] >= 0.0
    assert (tmp_path / "bus_summary.json").exists()
    assert (tmp_path / "figures" / "bus_features.png").exists()
