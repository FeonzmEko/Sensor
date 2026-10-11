"""采集质量检查：时间戳、间断、单位量级与标签映射。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .session import NS_PER_SECOND, SensorSession, SensorStream

GRAVITY = 9.80665


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _interval_stats(timestamp_ns: np.ndarray) -> dict[str, float]:
    if timestamp_ns.size < 2:
        return {
            "interval_us_min": 0.0,
            "interval_us_median": 0.0,
            "interval_us_p95": 0.0,
            "interval_us_p99": 0.0,
            "interval_us_max": 0.0,
        }
    interval_us = np.diff(timestamp_ns) / 1_000.0
    return {
        "interval_us_min": float(np.min(interval_us)),
        "interval_us_median": float(np.median(interval_us)),
        "interval_us_p95": float(np.percentile(interval_us, 95)),
        "interval_us_p99": float(np.percentile(interval_us, 99)),
        "interval_us_max": float(np.max(interval_us)),
    }


def check_stream(stream: SensorStream) -> dict[str, Any]:
    """对单个传感器做完整性 + 量级检查。"""
    frame = stream.frame
    timestamps = stream.timestamp_ns
    values = stream.values()
    magnitude = stream.magnitude()

    diff = np.diff(timestamps) if timestamps.size > 1 else np.empty(0, dtype=np.int64)
    duplicate_count = int(np.sum(diff == 0))
    regression_count = int(np.sum(diff < 0))
    strictly_monotonic = bool(np.all(diff > 0)) if diff.size else True

    stats = _interval_stats(timestamps)
    median_us = stats["interval_us_median"] or 0.0
    if median_us > 0 and diff.size:
        interval_us = diff / 1_000.0
        gaps_over_2x = int(np.sum(interval_us > 2 * median_us))
        gaps_over_3x = int(np.sum(interval_us > 3 * median_us))
    else:
        gaps_over_2x = gaps_over_3x = 0
    gaps_over_100ms = int(np.sum(diff > 100_000_000)) if diff.size else 0

    axes = {
        axis: {
            "mean": float(np.mean(values[:, index])),
            "stddev": float(np.std(values[:, index], ddof=0)),
            "min": float(np.min(values[:, index])),
            "max": float(np.max(values[:, index])),
        }
        for index, axis in enumerate(("x", "y", "z"))
    }

    result: dict[str, Any] = {
        "header_ok": True,
        "header": list(frame.columns),
        "sample_count": int(stream.sample_count),
        "first_timestamp_ns": int(timestamps[0]) if timestamps.size else None,
        "last_timestamp_ns": int(timestamps[-1]) if timestamps.size else None,
        "duration_seconds": float(stream.duration_seconds),
        "measured_hz": float(stream.measured_hz),
        "strictly_monotonic": strictly_monotonic,
        "duplicate_count": duplicate_count,
        "regression_count": regression_count,
        "gaps_over_2x_median": gaps_over_2x,
        "gaps_over_3x_median": gaps_over_3x,
        "gaps_over_100ms": gaps_over_100ms,
        "vector_mean": float(np.mean(magnitude)),
        "vector_stddev": float(np.std(magnitude, ddof=0)),
        "vector_min": float(np.min(magnitude)),
        "vector_max": float(np.max(magnitude)),
        "vector_p01": float(np.percentile(magnitude, 1)),
        "vector_p99": float(np.percentile(magnitude, 99)),
        "axes": axes,
        "first_row": [float(v) for v in frame.iloc[0].to_numpy(dtype=np.float64)],
        "last_row": [float(v) for v in frame.iloc[-1].to_numpy(dtype=np.float64)],
    }
    result.update(stats)

    if stream.name == "accelerometer":
        result["unit_check"] = {
            "expect": "m/s^2，静止合矢量接近 9.81",
            "vector_mean": float(np.mean(magnitude)),
            "static_like": bool(abs(float(np.mean(magnitude)) - GRAVITY) < 3.0),
            "max_range_observed": float(np.max(np.abs(values))),
            "saturation_risk": bool(np.max(magnitude) > 150.0),
        }
    else:
        result["unit_check"] = {
            "expect": "rad/s，静止接近 0",
            "vector_mean": float(np.mean(magnitude)),
            "vector_p99": float(np.percentile(magnitude, 99)),
            "max_range_observed": float(np.max(np.abs(values))),
            "saturation_risk": bool(np.max(magnitude) > 30.0),
        }
    return result


def check_labels(session: SensorSession) -> dict[str, Any]:
    """检查事件标签能否映射到最近的加速度计样本。"""
    labels = session.labels
    if labels.empty:
        return {
            "count": 0,
            "file": None,
            "max_offset_ms": None,
            "events": [],
            "note": "没有 labels.csv 或文件为空；全部区间按 unknown 处理。",
        }

    events = session.label_events()
    accel_times = session.accelerometer.time_seconds
    resolved = []
    max_offset_ms = 0.0
    for relative_seconds, label, _kind in events:
        index = int(np.argmin(np.abs(accel_times - relative_seconds)))
        offset_ms = abs(float(accel_times[index]) - relative_seconds) * 1_000.0
        max_offset_ms = max(max_offset_ms, offset_ms)
        resolved.append(
            {
                "label": label,
                "relative_seconds": float(relative_seconds),
                "nearest_accel_index": index,
                "nearest_accel_seconds": float(accel_times[index]),
                "offset_ms": offset_ms,
            }
        )
    return {
        "count": int(len(labels)),
        "file": session.labels_path.name if session.labels_path else None,
        "max_offset_ms": max_offset_ms,
        "events": resolved,
    }


def _overall_pass(report: dict[str, Any]) -> bool:
    for name, stream in report["sensors"].items():
        if not stream["header_ok"]:
            return False
        if not stream["strictly_monotonic"]:
            return False
        if stream["regression_count"] > 0:
            return False
        if stream["gaps_over_100ms"] > 0:
            return False
    return True


def build_quality_report(session: SensorSession) -> dict[str, Any]:
    report: dict[str, Any] = {
        "directory": str(session.directory),
        "session_id": session.session_id,
        "files": {},
        "sensors": {
            "accelerometer": check_stream(session.accelerometer),
            "gyroscope": check_stream(session.gyroscope),
        },
        "labels": check_labels(session),
        "metadata": session.metadata,
    }
    for name in ("accelerometer.csv", "gyroscope.csv", "metadata.json", "labels.csv"):
        path = session.directory / name
        if path.exists():
            report["files"][name] = {
                "size_bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
    report["overall_pass"] = _overall_pass(report)
    return report


def write_quality_report(session: SensorSession, out_path: str | Path) -> dict[str, Any]:
    report = build_quality_report(session)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
