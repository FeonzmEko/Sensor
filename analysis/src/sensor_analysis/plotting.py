"""绘图工具：波形、时域特征、FFT、D06/D07、公交防误计步。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .features_freq import single_sided_spectrum
from .session import SensorStream

# 让中文标题在常见字体下可显示，缺失时回退到英文字体而不报错。
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]


def _save(fig: plt.Figure, out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def plot_waveform(stream: SensorStream, out_path: str | Path, max_points: int = 6000) -> Path:
    times = stream.time_seconds
    values = stream.values()
    if times.size > max_points:
        step = max(1, times.size // max_points)
        times = times[::step]
        values = values[::step]

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    for index, axis in enumerate("xyz"):
        axes[0].plot(times, values[:, index], linewidth=0.7, label=f"{axis}")
    axes[0].set_ylabel("m/s²")
    axes[0].set_title(f"{stream.name} 原始三轴波形")
    axes[0].legend(loc="upper right", ncol=3)

    magnitude = np.sqrt(np.sum(values * values, axis=1))
    axes[1].plot(times, magnitude, linewidth=0.7, color="black")
    axes[1].set_xlabel("相对时间 / s")
    axes[1].set_ylabel("|a| / (m/s²)")
    axes[1].set_title("合矢量")
    return _save(fig, out_path)


def plot_time_features(features: pd.DataFrame, out_path: str | Path) -> Path:
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    x = features["start_seconds"]
    axes[0].plot(x, features["acc_mag_var"], color="tab:red")
    axes[0].set_ylabel("var")
    axes[0].set_title("滑窗时域特征（合矢量）")
    axes[1].plot(x, features["acc_mag_zcr_per_s"], color="tab:blue")
    axes[1].set_ylabel("ZCR / (次/s)")
    axes[2].plot(x, features["acc_mag_peak_dynamic"], color="tab:green")
    axes[2].set_ylabel("peak_dynamic")
    axes[2].set_xlabel("相对时间 / s")
    return _save(fig, out_path)


def plot_fft_spectrum(
    freqs: np.ndarray,
    amplitude: np.ndarray,
    f_peak: float,
    out_path: str | Path,
    title: str = "单边频谱",
    band: tuple[float, float] = (0.5, 3.0),
) -> Path:
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(freqs, amplitude, linewidth=0.9)
    ax.axvspan(band[0], band[1], color="orange", alpha=0.15, label=f"步频带 {band}")
    if f_peak > 0:
        ax.axvline(f_peak, color="red", linestyle="--", label=f"f_peak={f_peak:.3f} Hz")
    ax.set_xlabel("频率 / Hz")
    ax.set_ylabel("幅度")
    ax.set_title(title)
    ax.set_xlim(left=0)
    ax.legend(loc="upper right")
    return _save(fig, out_path)


def plot_time_frequency(
    time_seconds: np.ndarray,
    signal: np.ndarray,
    spectrum: dict[str, np.ndarray | float],
    out_path: str | Path,
    title: str = "时域 / 频域双联图",
) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    axes[0].plot(time_seconds, signal, linewidth=0.8, color="black")
    axes[0].set_xlabel("相对时间 / s")
    axes[0].set_ylabel("|a| / (m/s²)")
    axes[0].set_title("时域波形")
    axes[1].plot(spectrum["freqs"], spectrum["amplitude"], linewidth=0.9, color="tab:blue")
    f_peak = float(spectrum["f_peak_hz"])
    if f_peak > 0:
        axes[1].axvline(f_peak, color="red", linestyle="--", label=f"f_peak={f_peak:.3f} Hz")
        axes[1].legend(loc="upper right")
    axes[1].set_xlabel("频率 / Hz")
    axes[1].set_ylabel("幅度")
    axes[1].set_title("单边频谱")
    axes[1].set_xlim(left=0)
    fig.suptitle(title)
    return _save(fig, out_path)


def plot_d06(sweep: pd.DataFrame, out_path: str | Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))
    x = sweep["window_seconds"]
    axes[0].errorbar(x, sweep["var_mean"], yerr=sweep["var_std"], marker="o", capsize=3)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("窗长 W / s")
    axes[0].set_ylabel("方差均值 ± 标准差")
    axes[0].set_title("方差：短窗抖动、长窗钝化")

    axes[1].errorbar(x, sweep["zcr_mean"], yerr=sweep["zcr_std"], marker="o", capsize=3, color="tab:blue")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("窗长 W / s")
    axes[1].set_ylabel("ZCR / (次/s)")
    axes[1].set_title("过零率对窗长敏感")

    axes[2].plot(x, sweep["peak_mean"], marker="o", color="tab:green")
    axes[2].plot(x, sweep["peak_max"], marker="s", linestyle="--", color="tab:red")
    axes[2].set_xscale("log")
    axes[2].set_xlabel("窗长 W / s")
    axes[2].set_ylabel("动态峰值")
    axes[2].set_title("峰值：长窗更容易包含大冲击")
    fig.suptitle("D06 窗长/步进参数实验场")
    return _save(fig, out_path)


def plot_d07(records: list[dict[str, object]], out_path: str | Path) -> Path:
    fig, axes = plt.subplots(1, len(records), figsize=(3.6 * len(records), 3.8), squeeze=False)
    for ax, record in zip(axes[0], records):
        freqs = np.asarray(record["spectrum_freqs"], dtype=float)
        amplitude = np.asarray(record["spectrum_amplitude"], dtype=float)
        fs = float(record["fs_hz"])
        ax.plot(freqs, amplitude, color="tab:blue")
        ax.axvline(fs / 2.0, color="gray", linestyle=":", label="Nyquist")
        peak = float(record["f_peak_hz"])
        if peak > 0:
            ax.axvline(peak, color="red", linestyle="--", label=f"{peak:.2f} Hz")
        ax.set_title(f"fs={fs:g} Hz")
        ax.set_xlabel("频率 / Hz")
        ax.set_ylabel("幅度")
        ax.set_xlim(left=0)
        ax.legend(fontsize=8)
    fig.suptitle("D07 混叠实验：真值 2.8 Hz 在不同采样率下的主峰")
    return _save(fig, out_path)


def plot_gait_vs_vehicle(
    groups: Sequence[tuple[str, np.ndarray, np.ndarray, float]],
    out_path: str | Path,
    band: tuple[float, float] = (0.5, 3.0),
    max_frequency_hz: float = 12.0,
) -> Path:
    """两段数据的时域 / 频域并排对照。

    `groups` 每项为 (名称, 时间轴 / s, 合矢量信号 / m/s², 采样率 / Hz)。
    上图给出时域波形，下图给出完整的单边幅度谱（不截断到步频带），
    用于直观显示“时域幅度同量级、能量分布完全不同”。
    """
    assert len(groups) == 2, "该图固定对比两段数据"
    fig, axes = plt.subplots(2, 2, figsize=(13, 7), constrained_layout=True)
    for column, (name, time_seconds, signal, fs) in enumerate(groups):
        axis_time = axes[0][column]
        axis_time.plot(time_seconds, signal, linewidth=0.8, color="#1f77b4")
        axis_time.set_title(f"{name}：合矢量时域")
        axis_time.set_xlabel("窗内时间 / s")
        axis_time.set_ylabel("|a| / (m/s²)")

        freqs, amplitude = single_sided_spectrum(signal, fs)
        axis_freq = axes[1][column]
        axis_freq.plot(freqs, amplitude, linewidth=1.0, color="#d62728")
        keep = freqs <= max_frequency_hz
        axis_freq.axvspan(band[0], band[1], color="#2ca02c", alpha=0.15, label="步频带")
        axis_freq.set_xlim(0.0, max_frequency_hz)
        axis_freq.set_title(f"{name}：单边幅度谱")
        axis_freq.set_xlabel("频率 / Hz")
        axis_freq.set_ylabel("幅度")
        axis_freq.legend(fontsize=8)
        if np.any(keep):
            peak_index = int(np.argmax(amplitude[keep]))
            peak_frequency = float(freqs[keep][peak_index])
            axis_freq.axvline(peak_frequency, color="black", linestyle="--", linewidth=0.9)
            axis_freq.annotate(
                f"主峰 {peak_frequency:.2f} Hz",
                xy=(peak_frequency, float(amplitude[keep][peak_index])),
                xytext=(8, -12),
                textcoords="offset points",
                fontsize=8,
            )
    return _save(fig, out_path)

def plot_bus_features(
    walk_ratio: np.ndarray,
    walk_cv: np.ndarray,
    bus_ratio: np.ndarray,
    bus_cv: np.ndarray,
    out_path: str | Path,
    extra_groups: Sequence[tuple[str, np.ndarray, np.ndarray]] = (),
    walk_label: str = "步行（真实数据）",
) -> Path:
    """步行 / 乘车（参考） / 其它真实非步行状态的特征对照散点图。"""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    axes[0].scatter(walk_ratio, walk_cv, label=walk_label, alpha=0.5, s=14)
    axes[0].scatter(bus_ratio, bus_cv, label="乘车（仿真参考）", alpha=0.5, s=14, marker="^")
    for name, ratio, cv in extra_groups:
        axes[0].scatter(ratio, cv, label=f"{name}（真实数据）", alpha=0.55, s=16, marker="s")
    axes[0].set_xlabel("步频带能量占比 P(0.5~3)/P(0.5~10)")
    axes[0].set_ylabel("峰间隔变异系数 std/mean")
    axes[0].set_title("步行 vs 乘车特征散点")
    axes[0].legend(fontsize=8)

    bins = np.linspace(0, 1, 21)
    axes[1].hist(walk_ratio, bins=bins, alpha=0.6, label=walk_label.split("（")[0])
    axes[1].hist(bus_ratio, bins=bins, alpha=0.6, label="乘车（仿真）")
    for name, ratio, _cv in extra_groups:
        axes[1].hist(ratio, bins=bins, alpha=0.45, label=name)
    axes[1].set_xlabel("步频带能量占比")
    axes[1].set_ylabel("窗口数")
    axes[1].set_title("能量占比分布")
    axes[1].legend(fontsize=8)
    return _save(fig, out_path)


def plot_advanced_comparison(comparison: pd.DataFrame, out_path: str | Path) -> Path:
    """手工特征 / TSFresh 全特征 / SHAP top-k 的效果对比。"""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    positions = np.arange(len(comparison))
    axes[0].bar(positions - 0.2, comparison["macro_f1"], width=0.38, label="macro-F1")
    axes[0].bar(positions + 0.2, comparison["accuracy"], width=0.38, label="accuracy")
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels(
        [f"{name}\n({dim} 维)" for name, dim in zip(comparison["特征集"], comparison["dimension"])],
        fontsize=8,
    )
    axes[0].set_ylim(0.0, 1.05)
    axes[0].set_ylabel("指标")
    axes[0].set_title("三种特征集的分类效果")
    axes[0].legend(fontsize=8)

    axes[1].bar(positions, comparison["train_seconds"], color="#ff7f0e")
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels([f"{dim} 维" for dim in comparison["dimension"]], fontsize=8)
    axes[1].set_ylabel("训练耗时 / s")
    axes[1].set_title("训练耗时对比")
    for index, value in enumerate(comparison["train_seconds"]):
        axes[1].annotate(f"{value:.2f}s", (index, value), ha="center", va="bottom", fontsize=8)
    return _save(fig, out_path)


def plot_advanced_confusion(
    confusion: np.ndarray,
    classes: Sequence[str],
    out_path: str | Path,
) -> Path:
    """混淆矩阵热力图（含数值标注）。"""
    matrix = np.asarray(confusion, dtype=float)
    fig, axis = plt.subplots(figsize=(5.6, 5.0))
    image = axis.imshow(matrix, cmap="Blues")
    axis.set_xticks(np.arange(len(classes)))
    axis.set_yticks(np.arange(len(classes)))
    axis.set_xticklabels(classes, rotation=45, ha="right")
    axis.set_yticklabels(classes)
    axis.set_xlabel("预测")
    axis.set_ylabel("真值")
    axis.set_title("混淆矩阵（TSFresh top-k 轻量模型）")
    threshold = matrix.max() / 2.0 if matrix.size else 0.0
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            value = matrix[row, column]
            axis.text(
                column,
                row,
                f"{int(value)}",
                ha="center",
                va="center",
                fontsize=9,
                color="white" if value > threshold else "black",
            )
    fig.colorbar(image, ax=axis, shrink=0.85)
    return _save(fig, out_path)


def plot_advanced_shap(importance: pd.Series, out_path: str | Path) -> Path:
    """SHAP 平均绝对贡献 top-k 条形图。"""
    ordered = importance.sort_values()
    fig, axis = plt.subplots(figsize=(9, max(3.5, 0.32 * len(ordered))))
    axis.barh(
        [name.replace("__", "｜") for name in ordered.index],
        ordered.to_numpy(dtype=float),
        color="#2ca02c",
    )
    axis.set_xlabel("SHAP 平均绝对贡献")
    axis.set_title(f"自动特征 top-{len(ordered)}（按 SHAP 排序）")
    axis.tick_params(axis="y", labelsize=8)
    return _save(fig, out_path)
