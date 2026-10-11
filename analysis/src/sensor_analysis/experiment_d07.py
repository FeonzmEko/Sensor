"""D07 混叠实验：同一 2.8 Hz 信号在不同采样率下的主峰。

说明：课程 D07 页面给出的“fs = 2 Hz 得到 1.2 Hz 假峰”是 0.8 Hz 混叠峰关于
采样频率的镜像（fs - 0.8 = 1.2）。本实验同时给出标准奈奎斯特折叠结果与镜像值，
便于与页面答案对照，并在报告中解释两者的关系。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .features_freq import dominant_frequency
from .plotting import plot_d07

TRUE_FREQUENCY_HZ = 2.8
SAMPLE_RATES = (50.0, 5.0, 3.0, 2.0)


def fold_frequency(true_hz: float, fs: float) -> float:
    """把频率折叠到 [0, fs/2]（标准奈奎斯特折叠）。"""
    folded = float(np.mod(true_hz, fs))
    if folded > fs / 2.0:
        folded = fs - folded
    return folded


def run_alias_experiment(out_dir: str | Path, duration_seconds: float = 10.0) -> dict[str, object]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    for fs in SAMPLE_RATES:
        time = np.arange(0.0, duration_seconds, 1.0 / fs)
        signal = np.sin(2 * np.pi * TRUE_FREQUENCY_HZ * time)
        peak = dominant_frequency(signal, fs, band=(0.0, fs / 2.0), use_hann=True)
        alias = fold_frequency(TRUE_FREQUENCY_HZ, fs)
        records.append(
            {
                "fs_hz": float(fs),
                "nyquist_hz": float(fs / 2.0),
                "true_frequency_hz": TRUE_FREQUENCY_HZ,
                "f_peak_hz": float(peak.frequency_hz),
                "step_frequency_spm": float(peak.step_frequency_spm),
                "resolution_hz": float(peak.resolution_hz),
                "folded_alias_hz": float(alias),
                "mirror_about_fs_hz": float(fs - alias),
                "spectrum_freqs": peak.spectrum_freqs,
                "spectrum_amplitude": peak.spectrum_amplitude,
            }
        )

    figure = plot_d07(records, out / "figures" / "d07_alias.png")
    fs2 = next(item for item in records if item["fs_hz"] == 2.0)

    summary = {
        "true_frequency_hz": TRUE_FREQUENCY_HZ,
        "sample_rates_hz": list(SAMPLE_RATES),
        "records": [{k: v for k, v in item.items() if not k.startswith("spectrum_")} for item in records],
        "figure": str(figure),
        "course_check": {
            "expected_mirror_alias_hz": 1.2,
            "observed_mirror_about_fs_hz": fs2["mirror_about_fs_hz"],
            "observed_standard_alias_hz": fs2["folded_alias_hz"],
            "note": (
                "标准奈奎斯特折叠把 2.8 Hz 在 fs=2 Hz 下折到 0.8 Hz；"
                "讲义页面给出的 1.2 Hz 是镜像值 fs-0.8。实验输出两者供对照。"
            ),
        },
        "conclusions": {
            "folding_start": "当 fs=5 Hz 时奈奎斯特频率 2.5 Hz < 2.8 Hz，主峰开始折返到 2.2 Hz。",
            "alias_chain": "现象：步数少算一半 → 指标：主峰降到 0.8/1.2 Hz → 谱：能量出现在混叠频率 → 采样率：fs=2 Hz 远低于 2×2.8 Hz。",
            "nyquist_rule": "只有 fs > 2 × f_max 才不发生混叠；行人步频带按 3 Hz 计，fs 应大于 6 Hz。",
        },
    }
    (out / "d07_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary
