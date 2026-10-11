"""绘图工具：波形、时域特征、FFT、D06/D07、公交防误计步。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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


def plot_bus_features(
    walk_ratio: np.ndarray,
    walk_cv: np.ndarray,
    bus_ratio: np.ndarray,
    bus_cv: np.ndarray,
    out_path: str | Path,
) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    axes[0].scatter(walk_ratio, walk_cv, label="步行（真实数据）", alpha=0.5, s=14)
    axes[0].scatter(bus_ratio, bus_cv, label="乘车（仿真参考）", alpha=0.5, s=14, marker="^")
    axes[0].set_xlabel("步频带能量占比 P(0.5~3)/P(0.5~10)")
    axes[0].set_ylabel("峰间隔变异系数 std/mean")
    axes[0].set_title("步行 vs 乘车特征散点")
    axes[0].legend()

    bins = np.linspace(0, 1, 21)
    axes[1].hist(walk_ratio, bins=bins, alpha=0.6, label="步行")
    axes[1].hist(bus_ratio, bins=bins, alpha=0.6, label="乘车（仿真）")
    axes[1].set_xlabel("步频带能量占比")
    axes[1].set_ylabel("窗口数")
    axes[1].set_title("能量占比分布")
    axes[1].legend()
    return _save(fig, out_path)
