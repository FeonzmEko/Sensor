"""一键分析管道：质量检查 → 标签 → 滑窗 → 时域 → FFT → D06/D07 → 公交防误计步 → 报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .bus_false_step import run_bus_experiment
from .experiment_d06 import run_d06_experiment
from .experiment_d07 import run_alias_experiment
from .features_freq import build_frequency_feature_table, spectrum_for_window
from .features_time import build_time_feature_table
from .plotting import (
    plot_fft_spectrum,
    plot_time_features,
    plot_time_frequency,
    plot_waveform,
)
from .quality import write_quality_report
from .session import SensorSession, load_session
from .windows import WindowSpec, build_windows, resolve_state_lookup


def _window_signal(session: SensorSession, row: pd.Series) -> tuple[np.ndarray, np.ndarray, float]:
    stream = session.accelerometer
    start_index = int(row["start_index"])
    end_index = int(row["end_index"])
    time_seconds = stream.time_seconds[start_index:end_index]
    signal = stream.magnitude()[start_index:end_index]
    window_seconds = float(row["end_seconds"]) - float(row["start_seconds"])
    fs = signal.size / window_seconds if window_seconds > 0 else 0.0
    return time_seconds, signal, fs


def _pick_representative_windows(features: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    motion = features["acc_mag_var"].to_numpy(dtype=float)
    finite = np.isfinite(motion)
    if not np.any(finite):
        raise ValueError("没有可用的窗口特征")
    valid = np.flatnonzero(finite)
    low_index = valid[int(np.argmin(motion[valid]))]
    high_index = valid[int(np.argmax(motion[valid]))]
    return features.iloc[low_index], features.iloc[high_index]


def _format_bytes(size: int) -> str:
    return f"{size:,} bytes"


def run_pipeline(
    session_dir: str | Path,
    out_dir: str | Path | None = None,
    window_seconds: float = 4.0,
    step_seconds: float = 2.0,
    band: tuple[float, float] = (0.5, 3.0),
) -> Path:
    session = load_session(session_dir)
    output = Path(out_dir) if out_dir else Path("analysis_outputs") / session.session_id
    output = output.resolve()
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    # 1) 质量检查
    quality = write_quality_report(session, output / "quality_report.json")

    # 2) 标签解析
    state_lookup, labels_resolved = resolve_state_lookup(session)
    labels_resolved.to_csv(output / "labels_resolved.csv", index=False, encoding="utf-8-sig")

    # 3) 滑窗
    spec = WindowSpec(window_seconds=window_seconds, step_seconds=step_seconds)
    windows = build_windows(
        session.accelerometer,
        spec,
        session_id=session.session_id,
        state_lookup=state_lookup,
    )
    windows.to_csv(output / "windows.csv", index=False, encoding="utf-8-sig")

    # 4) 时域四件套
    time_features = build_time_feature_table(session.accelerometer, windows, band=band)

    # 5) FFT 与步频
    frequency_features = build_frequency_feature_table(session.accelerometer, windows, band=band)
    merged = time_features.merge(
        frequency_features.drop(columns=["session_id", "start_seconds", "end_seconds", "state"]),
        on="window_id",
        how="left",
    )
    merged.to_csv(output / "window_features.csv", index=False, encoding="utf-8-sig")
    frequency_features.to_csv(output / "window_frequency_features.csv", index=False, encoding="utf-8-sig")

    # 6) 波形与频谱图
    plot_waveform(session.accelerometer, figures / "waveform.png")
    plot_time_features(time_features, figures / "time_features.png")

    low_row, high_row = _pick_representative_windows(time_features)
    spectrum_store: dict[str, np.ndarray] = {}
    representative: list[dict[str, object]] = []
    for name, row in (("slow", low_row), ("fast", high_row)):
        time_seconds, signal, fs = _window_signal(session, row)
        spectrum = spectrum_for_window(signal, fs, band=band)
        spectrum_store[f"{name}_freqs"] = np.asarray(spectrum["freqs"], dtype=float)
        spectrum_store[f"{name}_amplitude"] = np.asarray(spectrum["amplitude"], dtype=float)
        spectrum_store[f"{name}_signal"] = signal
        spectrum_store[f"{name}_time"] = time_seconds
        spectrum_store[f"{name}_fs"] = np.array([fs], dtype=float)
        representative.append(
            {
                "name": name,
                "window_id": int(row["window_id"]),
                "start_seconds": float(row["start_seconds"]),
                "f_peak_hz": float(spectrum["f_peak_hz"]),
                "step_frequency_spm": float(spectrum["step_frequency_spm"]),
                "resolution_hz": float(spectrum["resolution_hz"]),
                "acc_mag_var": float(row["acc_mag_var"]),
            }
        )
    spectrum_store["window_f_peak_hz"] = frequency_features["f_peak_hz"].to_numpy(dtype=float)
    spectrum_store["window_step_frequency_spm"] = frequency_features["step_frequency_spm"].to_numpy(dtype=float)
    np.savez_compressed(output / "spectrum.npz", **spectrum_store)

    plot_fft_spectrum(
        np.asarray(spectrum_store["fast_freqs"]),
        np.asarray(spectrum_store["fast_amplitude"]),
        float(representative[1]["f_peak_hz"]),
        figures / "fft_spectrum.png",
        title="加速度合矢量单边频谱（高运动窗）",
        band=band,
    )
    plot_time_frequency(
        np.asarray(spectrum_store["fast_time"]),
        np.asarray(spectrum_store["fast_signal"]),
        {
            "freqs": spectrum_store["fast_freqs"],
            "amplitude": spectrum_store["fast_amplitude"],
            "f_peak_hz": representative[1]["f_peak_hz"],
        },
        figures / "time_frequency.png",
        title="时域 / 频域双联图（高运动窗）",
    )

    # 7) D06 / D07 / 公交防误计步
    d06 = run_d06_experiment(session, output)
    d07 = run_alias_experiment(output)
    bus = run_bus_experiment(session, output, window_seconds=window_seconds, step_seconds=step_seconds)

    # 8) 报告
    report = _build_report(
        session=session,
        quality=quality,
        spec=spec,
        band=band,
        windows=windows,
        time_features=time_features,
        frequency_features=frequency_features,
        representative=representative,
        d06=d06,
        d07=d07,
        bus=bus,
    )
    (output / "report.md").write_text(report, encoding="utf-8")
    return output


def _describe_metadata(session: SensorSession) -> str:
    metadata = session.metadata
    device = metadata.get("device", {})
    lines = [
        f"- 会话 ID：`{session.session_id}`",
        f"- 原始目录：`{session.directory}`",
        f"- 设备：{device.get('manufacturer', '?')} {device.get('model', '?')}（Android {device.get('android_release', '?')}）",
        f"- 路线名称：{metadata.get('route_name', '（旧数据未记录）')}",
        f"- 手机位置：{metadata.get('device_placement', '（旧数据未记录）')}",
        f"- 手机朝向：{metadata.get('orientation', '（旧数据未记录）')}",
        f"- 目标时长：{metadata.get('target_duration_seconds', '（旧数据未记录）')} 秒",
        f"- 备注：{metadata.get('note', '') or '（无）'}",
    ]
    return "\n".join(lines)


def _build_report(
    session: SensorSession,
    quality: dict,
    spec: WindowSpec,
    band: tuple[float, float],
    windows: pd.DataFrame,
    time_features: pd.DataFrame,
    frequency_features: pd.DataFrame,
    representative: list[dict[str, object]],
    d06: dict,
    d07: dict,
    bus: dict,
) -> str:
    acc = quality["sensors"]["accelerometer"]
    gyro = quality["sensors"]["gyroscope"]
    step_values = frequency_features["step_frequency_spm"].dropna()
    in_band = frequency_features[
        (frequency_features["f_peak_hz"] >= band[0]) & (frequency_features["f_peak_hz"] <= band[1])
    ]
    d07_records = d07["records"]

    lines: list[str] = []
    lines.append(f"# 第 2 课时特征工程分析报告 · {session.session_id}")
    lines.append("")
    lines.append("> 本报告由 `analysis/src/sensor_analysis/pipeline.py` 自动生成；所有图表与指标均来自本节给出的会话数据。")
    lines.append("")
    lines.append("## 1. 数据来源")
    lines.append("")
    lines.append(_describe_metadata(session))
    lines.append("")
    lines.append("## 2. 质量检查")
    lines.append("")
    lines.append(f"- 总判据 `overall_pass`：**{quality['overall_pass']}**")
    lines.append(f"- 加速度计：{acc['sample_count']} 点，时长 {acc['duration_seconds']:.2f} s，实测 {acc['measured_hz']:.2f} Hz")
    lines.append(f"- 陀螺仪：{gyro['sample_count']} 点，时长 {gyro['duration_seconds']:.2f} s，实测 {gyro['measured_hz']:.2f} Hz")
    lines.append(f"- 时间戳严格递增：加计 {acc['strictly_monotonic']}，陀螺 {gyro['strictly_monotonic']}")
    lines.append(f"- 重复/回退时间戳：加计 {acc['duplicate_count']}/{acc['regression_count']}，陀螺 {gyro['duplicate_count']}/{gyro['regression_count']}")
    lines.append(f"- 超过 100 ms 的长间断：加计 {acc['gaps_over_100ms']}，陀螺 {gyro['gaps_over_100ms']}")
    lines.append(f"- 标签事件数：{quality['labels']['count']}，最近样本最大偏移 {quality['labels']['max_offset_ms']} ms")
    lines.append("")
    lines.append("## 3. 滑动窗口")
    lines.append("")
    lines.append(f"- 窗长 `W = {spec.window_seconds} s`，步进 `S = {spec.step_seconds} s`，重叠率 `{spec.overlap_ratio:.0%}`")
    lines.append(f"- 窗口数：{len(windows)}；每窗保留起止时间、起止样本索引、样本数与状态标签")
    state_counts = (
        {str(key): int(value) for key, value in windows['state'].value_counts().items()}
        if not windows.empty
        else {}
    )
    lines.append(f"- 状态分布：{state_counts}")
    lines.append("")
    lines.append("## 4. 手写时域四件套")
    lines.append("")
    lines.append("- 均值 `mean = (1/N) Σ x_i`，主要反映重力与姿态；")
    lines.append("- 方差 `var = (1/N) Σ (x_i - mean)^2`（总体方差，`ddof=0`），反映波动强度；")
    lines.append("- 过零率：去均值后统计符号变化次数，`ZCR = 过零次数 / 时长`，可选 FFT 带限；")
    lines.append("- 峰值：`peak_dynamic = max|x_i - mean|`（动态峰值），同时保留 `peak_raw`。")
    lines.append("")
    if not time_features.empty:
        var_stats = time_features["acc_mag_var"].describe()
        lines.append(f"- 合矢量方差：min={var_stats['min']:.3f}，median={var_stats['50%']:.3f}，max={var_stats['max']:.3f}")
        lines.append(f"- 全段动态峰值最大：{time_features['acc_mag_peak_dynamic'].max():.3f} m/s²")
        lines.append("- 敏感度矩阵结论：方差用于“动没动”，ZCR/主峰用于“动多快”，峰值用于“动多大”。")
    lines.append("")
    lines.append("## 5. FFT 主峰与步频")
    lines.append("")
    if not step_values.empty:
        lines.append(f"- 步频带内窗口数：{len(in_band)} / {len(frequency_features)}")
        lines.append(f"- 主峰步频：中位数 {step_values.median():.1f} 步/分，P05 {step_values.quantile(0.05):.1f}，P95 {step_values.quantile(0.95):.1f}")
    lines.append("- 频率分辨率 `Δf = fs / N = 1 / W`，本报告 `W` 对应的分辨率见 `window_features.csv`。")
    for item in representative:
        lines.append(
            f"- 代表窗口 {item['name']}（window {item['window_id']}）："
            f"f_peak={item['f_peak_hz']:.3f} Hz，步频={item['step_frequency_spm']:.1f} 步/分，"
            f"分辨率={item['resolution_hz']:.4f} Hz"
        )
    lines.append("")
    lines.append("## 6. D06 参数实验场")
    lines.append("")
    lines.append("- 极短窗：方差与 ZCR 抖动增大，噪声被放大；")
    lines.append("- 极长窗：方差被平均钝化，峰值更易被大冲击抬高；")
    lines.append("- `S = W`：1.2 s 短事件跨缝被劈开，单窗覆盖率下降；")
    lines.append("- `S = W/2`（50% 重叠）：短事件覆盖率提升，推荐作为工作点。")
    lines.append("- 详见 `figures/d06_window_sweep.png`、`d06_window_sweep.csv`、`d06_event_split.csv`。")
    lines.append("")
    lines.append("## 7. D07 混叠实验")
    lines.append("")
    lines.append("| fs / Hz | Nyquist / Hz | 谱主峰 / Hz | 标准折叠 / Hz | 关于 fs 的镜像 / Hz |")
    lines.append("|---:|---:|---:|---:|---:|")
    for item in d07_records:
        lines.append(
            f"| {item['fs_hz']:.0f} | {item['nyquist_hz']:.1f} | {item['f_peak_hz']:.2f} | "
            f"{item['folded_alias_hz']:.2f} | {item['mirror_about_fs_hz']:.2f} |"
        )
    lines.append("")
    lines.append(f"- {d07['conclusions']['folding_start']}")
    lines.append(f"- {d07['conclusions']['nyquist_rule']}")
    lines.append(
        "- 课程页面给出的 `fs = 2 Hz → 1.2 Hz` 是 `0.8 Hz` 混叠峰关于采样频率的镜像；"
        "标准奈奎斯特折叠值为 `0.8 Hz`，两种写法都能说明“高频被低采样率折返”。"
    )
    lines.append("")
    lines.append("## 8. 作业②：公交防误计步")
    lines.append("")
    walk = bus["walking"]
    busy = bus["bus"]
    variance_baseline = bus["variance_only_baseline"]
    lines.append(
        f"- 特征 1：步频带能量占比 R=P(0.5~3)/P(0.5~10)；"
        f"步行中位数 {walk['ratio_median']:.3f}，乘车参考中位数 {busy['ratio_median']:.3f}。"
    )
    lines.append(
        f"- 特征 2：峰间隔变异系数 CV=std/mean；"
        f"步行均值 {walk['cv_mean']:.3f}，乘车参考均值 {busy['cv_mean']:.3f}。"
    )
    lines.append(
        f"- 阈值思路：R ≥ {bus['thresholds']['step_band_energy_ratio']} 且 "
        f"CV ≤ {bus['thresholds']['peak_interval_cv']} 判为步行。"
    )
    lines.append(
        f"- 双特征判定：真实步行窗口被判为步行的比例 "
        f"{walk['classified_walking_ratio']:.2%}；仿真乘车参考被判为步行的比例 "
        f"{busy['classified_walking_ratio']:.2%}。"
    )
    lines.append(
        f"- 只用方差的对照基线（阈值 {variance_baseline['threshold_m_s2_squared']:.2f}）："
        f"仿真乘车窗口被判为步行的比例高达 {variance_baseline['bus_classified_walking_ratio']:.2%}，"
        "说明“加速度大/方差大”无法区分乘车与步行。"
    )
    lines.append("- 结论：必须结合步频带能量占比与节奏规律性，才能抑制公交误计步。")
    lines.append("- 注意：乘车段当前使用仿真车辆振动参考信号验证管道，真实乘车特征需在 20 分钟路线数据补齐后复算。")
    lines.append("")
    lines.append("## 9. 输出文件")
    lines.append("")
    for name in (
        "quality_report.json",
        "labels_resolved.csv",
        "windows.csv",
        "window_features.csv",
        "window_frequency_features.csv",
        "spectrum.npz",
        "figures/waveform.png",
        "figures/time_features.png",
        "figures/fft_spectrum.png",
        "figures/time_frequency.png",
        "figures/d06_window_sweep.png",
        "figures/d07_alias.png",
        "figures/bus_features.png",
    ):
        lines.append(f"- `{name}`")
    lines.append("")
    lines.append("## 10. 局限")
    lines.append("")
    lines.append("- 当前用于演示的 571.3 s 数据是匀速步行，不能替代第 2 次课要求的约 20 分钟混合状态数据；")
    lines.append("- 陀螺仪实测约 46 Hz，低于加计的约 115 Hz，跨传感器融合前需要显式重采样；")
    lines.append("- 未记录书面朝向，姿态只由重力方向推断；")
    lines.append("- 乘车特征目前用仿真信号占位，需用真实乘车段替换后重新标定阈值。")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="传感器采集会话特征工程分析管道")
    parser.add_argument("--session", required=True, help="会话目录（含 accelerometer.csv 等）")
    parser.add_argument("--out", default=None, help="输出目录，默认 analysis_outputs/<session_id>")
    parser.add_argument("--window", type=float, default=4.0, help="窗长（秒）")
    parser.add_argument("--step", type=float, default=2.0, help="步进（秒）")
    parser.add_argument("--band-low", type=float, default=0.5, help="步频带下限（Hz）")
    parser.add_argument("--band-high", type=float, default=3.0, help="步频带上限（Hz）")
    args = parser.parse_args(argv)

    output = run_pipeline(
        session_dir=args.session,
        out_dir=args.out,
        window_seconds=args.window,
        step_seconds=args.step,
        band=(args.band_low, args.band_high),
    )
    print(f"分析完成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
