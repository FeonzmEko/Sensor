"""进阶加分：TSFresh 自动特征 + XGBoost / SHAP 特征筛选。

流程：
1. 只用“纯窗口”（整窗落在同一个打点状态内），丢弃跨状态边界与被标为 `过渡` 的窗口；
2. 把逐样本数据整理成长表 `(id, time, kind, value)`，通道含加速度计三轴与合矢量，
   可选把 46 Hz 的陀螺仪线性插值到加计时基上；
3. 用 TSFresh 的 `EfficientFCParameters` 提取自动特征，记录参数、耗时与维度；
4. 清洗：`inf → NaN`、丢弃全空列、剩余缺失用列中位数填补、丢弃常量列；
5. 按“状态区间”划分训练 / 验证集（同一段连续数据不会同时落在两边，
   单个区间的状态在切分点丢掉 W 秒保护带），并程序化校验无重叠窗口泄漏；
6. 用 XGBoost 训练多分类器，输出 gain 重要性与 SHAP top-k 贡献；
7. 用 top-k 特征重训轻量模型，与手工四件套 / 频域特征比较维度、耗时与指标。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .plotting import plot_advanced_comparison, plot_advanced_confusion, plot_advanced_shap
from .session import (
    STATE_ALIASES,
    TRANSITION_STATE,
    SensorSession,
    build_state_intervals,
    load_session,
)
from .windows import WindowSpec, iter_window_bounds

DEFAULT_CHANNELS: tuple[str, ...] = ("acc_x", "acc_y", "acc_z", "acc_mag")
GYRO_CHANNELS: tuple[str, ...] = ("gyro_x", "gyro_y", "gyro_z", "gyro_mag")

#: 手工特征（时域四件套 + 频域）用于与自动特征对比。
HANDCRAFTED_PREFIXES: tuple[str, ...] = ("acc_",)
HANDCRAFTED_COLUMNS: tuple[str, ...] = (
    "f_peak_hz",
    "f_peak_amplitude",
    "step_frequency_spm",
    "step_band_energy_ratio",
    "peak_count",
    "interval_mean_s",
    "interval_std_s",
    "interval_cv",
    "interval_frequency_hz",
)

#: 自动特征族划分：按关键字匹配特征名，**从上到下第一个命中者生效**。
#: 划分规则写进报告，便于复核；顺序会影响结果，因此先判频域与熵，再判方差/极值，
#: 最后才是计数与趋势形态。
FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "频域聚合量族": (
        "fft_coefficient",
        "fft_aggregated",
        "spkt_welch_density",
        "spectral",
        "autocorrelation",
        "cwt_coefficients",
        "fourier",
        "lpcc",
    ),
    "熵与复杂度族": (
        "entropy",
        "cid_ce",
        "lempel_ziv",
        "complexity",
        "dfa",
        "augmented_dickey",
    ),
    "方差族": (
        "variance",
        "standard_deviation",
        "variation",
        "abs_energy",
        "root_mean_square",
        "mean_abs_change",
        "mean_change",
        "absolute_sum_of_changes",
        "energy_ratio",
        "ratio_beyond_r_sigma",
        "index_mass_quantile",
    ),
    "极值族": ("maximum", "minimum", "peak", "count_above", "count_below", "longest_strike"),
    "计数与分位族": (
        "count",
        "number",
        "quantile",
        "median",
        "sum_values",
        "sum_of_reoccurring",
        "has_",
        "unique",
        "duplicate",
        "value_count",
        "range_count",
        "benford",
    ),
    "趋势与形态族": (
        "skewness",
        "kurtosis",
        "linear_trend",
        "ar_coefficient",
        "partial_autocorrelation",
        "chi2",
        "symmetry",
        "change_quantiles",
        "mean",
    ),
}


def _sha256(path: Path) -> str:
    """计算文件 SHA-256，用于标记可复现的中间产物。"""
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def feature_family(column: str) -> str:
    """按特征名判断它属于哪个特征族。"""
    name = column.split("__", 1)[-1].lower()
    for family, keywords in FEATURE_FAMILIES.items():
        if any(keyword in name for keyword in keywords):
            return family
    return "其它"


#: 把「上楼梯 / 下楼梯」拆成两个独立状态的别名表（默认仍合并为 `楼梯`）。
SEPARATE_STAIRS_ALIASES: dict[str, str] = {
    **STATE_ALIASES,
    "上楼梯": "上楼梯",
    "下楼梯": "下楼梯",
}


def build_pure_windows(
    session: SensorSession,
    spec: WindowSpec,
    aliases: dict[str, str] | None = None,
) -> pd.DataFrame:
    """只保留整窗落在同一个打点状态内的窗口，并给出所属区间编号。"""
    intervals = [
        (state, start, end)
        for state, start, end in build_state_intervals(
            session.label_events(), session.duration_seconds, aliases
        )
        if state not in ("unknown", TRANSITION_STATE)
    ]

    rows: list[dict[str, object]] = []
    for window_id, start, end in iter_window_bounds(session.duration_seconds, spec):
        for index, (state, seg_start, seg_end) in enumerate(intervals):
            if seg_start - 1e-9 <= start and end <= seg_end + 1e-9:
                rows.append(
                    {
                        "window_id": window_id,
                        "start_seconds": float(start),
                        "end_seconds": float(end),
                        "state": state,
                        "segment_id": f"{state}-{index:02d}",
                    }
                )
                break

    frame = pd.DataFrame(
        rows,
        columns=["window_id", "start_seconds", "end_seconds", "state", "segment_id"],
    )
    stream = session.accelerometer
    times = stream.time_seconds
    frame["start_index"] = np.searchsorted(times, frame["start_seconds"], side="left")
    frame["end_index"] = np.searchsorted(times, frame["end_seconds"], side="left")
    return frame


def _channel_series(session: SensorSession, channels: tuple[str, ...]) -> dict[str, np.ndarray]:
    """把需要的通道对齐到加速度计时间轴（陀螺仪线性插值，只影响派生序列）。"""
    stream = session.accelerometer
    ax = stream.frame["x_m_s2"].to_numpy(dtype=float)
    ay = stream.frame["y_m_s2"].to_numpy(dtype=float)
    az = stream.frame["z_m_s2"].to_numpy(dtype=float)
    arrays: dict[str, np.ndarray] = {
        "acc_x": ax,
        "acc_y": ay,
        "acc_z": az,
        "acc_mag": stream.magnitude(),
    }
    if any(name.startswith("gyro") for name in channels):
        gyro = session.gyroscope
        gx = gyro.frame["x_rad_s"].to_numpy(dtype=float)
        gy = gyro.frame["y_rad_s"].to_numpy(dtype=float)
        gz = gyro.frame["z_rad_s"].to_numpy(dtype=float)
        raw = {"gyro_x": gx, "gyro_y": gy, "gyro_z": gz, "gyro_mag": gyro.magnitude()}
        source_time = gyro.time_seconds
        target_time = stream.time_seconds
        for name, values in raw.items():
            arrays[name] = np.interp(target_time, source_time, values)
    missing = [name for name in channels if name not in arrays]
    if missing:
        raise ValueError(f"未知通道：{missing}")
    return arrays


def build_long_table(
    session: SensorSession,
    windows: pd.DataFrame,
    channels: tuple[str, ...] = DEFAULT_CHANNELS,
) -> pd.DataFrame:
    """整理成 TSFresh 需要的长表：列 = id / time / kind / value。"""
    arrays = _channel_series(session, channels)
    time_axis = session.accelerometer.time_seconds
    frames: list[pd.DataFrame] = []
    for row in windows.itertuples(index=False):
        start_index = int(row.start_index)
        end_index = int(row.end_index)
        window_time = time_axis[start_index:end_index] - time_axis[start_index]
        for name in channels:
            frames.append(
                pd.DataFrame(
                    {
                        "id": int(row.window_id),
                        "time": window_time,
                        "kind": name,
                        "value": arrays[name][start_index:end_index],
                    }
                )
            )
    long_table = pd.concat(frames, ignore_index=True)
    return long_table.sort_values(["id", "kind", "time"], kind="stable").reset_index(drop=True)


def extract_tsfresh_features(
    long_table: pd.DataFrame,
    fc_parameters: str = "efficient",
    n_jobs: int = 0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """调用 TSFresh 提取自动特征，并记录参数与耗时。"""
    from tsfresh import extract_features
    from tsfresh.feature_extraction import EfficientFCParameters, MinimalFCParameters

    settings = {
        "efficient": EfficientFCParameters,
        "minimal": MinimalFCParameters,
    }.get(fc_parameters)
    if settings is None:
        raise ValueError(f"未知的 fc_parameters：{fc_parameters}")

    started = time.perf_counter()
    features = extract_features(
        long_table,
        column_id="id",
        column_sort="time",
        column_kind="kind",
        column_value="value",
        default_fc_parameters=settings(),
        n_jobs=n_jobs,
        disable_progressbar=True,
        show_warnings=False,
    )
    elapsed = time.perf_counter() - started
    meta = {
        "fc_parameters": fc_parameters,
        "n_jobs": n_jobs,
        "extract_seconds": round(elapsed, 2),
        "rows": int(features.shape[0]),
        "raw_dimension": int(features.shape[1]),
        "tsfresh_version": _module_version("tsfresh"),
    }
    return features, meta


def _module_version(name: str) -> str | None:
    try:
        module = __import__(name)
    except ImportError:  # pragma: no cover - 依赖缺失时只记录为空
        return None
    return getattr(module, "__version__", None)


def clean_feature_matrix(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """inf → NaN、丢全空列、中位数填补、丢常量列，并记录每一步的影响。"""
    report: dict[str, object] = {
        "rows": int(features.shape[0]),
        "raw_dimension": int(features.shape[1]),
    }
    matrix = features.replace([np.inf, -np.inf], np.nan)
    report["non_finite_cells"] = int(matrix.isna().to_numpy().sum())

    all_nan = matrix.columns[matrix.isna().all()].tolist()
    matrix = matrix.drop(columns=all_nan)
    report["dropped_all_nan_columns"] = len(all_nan)
    report["dropped_all_nan_examples"] = all_nan[:5]

    filled_cells = int(matrix.isna().to_numpy().sum())
    if filled_cells:
        matrix = matrix.fillna(matrix.median(numeric_only=True))
    report["filled_cells"] = filled_cells

    nunique = matrix.nunique(dropna=False)
    constant = nunique[nunique <= 1].index.tolist()
    matrix = matrix.drop(columns=constant)
    report["dropped_constant_columns"] = len(constant)
    report["final_dimension"] = int(matrix.shape[1])
    return matrix, report


def split_windows(
    meta: pd.DataFrame,
    window_seconds: float = 4.0,
    step_seconds: float = 2.0,
    test_fraction: float = 0.3,
    guard_seconds: float | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """在每个状态区间内部做带保护带的时间切分。

    每个区间按时间前后切分，切分点两侧各丢一段保护带，因此训练窗口与验证窗口
    在时间轴上永不重叠（`check_no_overlap` 会程序化校验），同时每个状态都能同时
    出现在训练集和验证集中。保护带默认取一个窗长 `W`；若区间太短、切完一侧为空，
    依次退让成 `W/2`、步进 `S`，并把验证比例放宽到 50%（用于只有 20 s 的静止段）。
    仍然无法两边都有窗口时，该区间全部进训练集，并在 `per_segment` 中记录。
    """
    guard = float(window_seconds if guard_seconds is None else guard_seconds)
    train_ids: list[int] = []
    test_ids: list[int] = []
    dropped = 0
    detail: dict[str, dict[str, object]] = {}

    for segment, group in meta.groupby("segment_id", sort=True):
        ordered = group.sort_values("start_seconds")
        span_start = float(ordered["start_seconds"].min())
        span_end = float(ordered["end_seconds"].max())

        chosen: tuple[float, float, float, list[int], list[int]] | None = None
        for candidate_guard, candidate_fraction in (
            (guard, test_fraction),
            (guard / 2.0, test_fraction),
            (step_seconds, test_fraction),
            (step_seconds, 0.5),
        ):
            if candidate_guard <= 0.0:
                continue
            cut = span_start + (span_end - span_start) * (1.0 - candidate_fraction)
            segment_train = ordered.loc[
                ordered["end_seconds"] <= cut - candidate_guard, "window_id"
            ].tolist()
            segment_test = ordered.loc[
                ordered["start_seconds"] >= cut + candidate_guard, "window_id"
            ].tolist()
            if segment_train and segment_test:
                chosen = (candidate_guard, candidate_fraction, cut, segment_train, segment_test)
                break

        if chosen is None:
            cut = span_start + (span_end - span_start) * (1.0 - test_fraction)
            segment_train = ordered["window_id"].tolist()
            segment_test = []
            used_guard, used_fraction = guard, test_fraction
        else:
            used_guard, used_fraction, cut, segment_train, segment_test = chosen

        dropped += int(len(ordered) - len(segment_train) - len(segment_test))
        train_ids.extend(segment_train)
        test_ids.extend(segment_test)
        detail[str(segment)] = {
            "state": str(ordered["state"].iloc[0]),
            "windows": int(len(ordered)),
            "train": len(segment_train),
            "test": len(segment_test),
            "cut_seconds": round(cut, 2),
            "guard_seconds": used_guard,
            "test_fraction_used": used_fraction,
        }

    return (
        np.asarray(train_ids),
        np.asarray(test_ids),
        {
            "mode": "per-segment guard split",
            "train_windows": len(train_ids),
            "test_windows": len(test_ids),
            "guard_seconds": guard,
            "test_fraction": test_fraction,
            "dropped_by_guard": dropped,
            "per_segment": detail,
        },
    )


def leave_one_segment_out(
    meta: pd.DataFrame,
    min_test_windows: int = 3,
) -> list[dict[str, object]]:
    """每个状态区间轮流当验证集，衡量“换一段没见过的地形”时的泛化能力。"""
    segment_count = meta.groupby("state")["segment_id"].nunique()
    folds: list[dict[str, object]] = []
    for segment in sorted(meta["segment_id"].unique()):
        mask = meta["segment_id"] == segment
        state = str(meta.loc[mask, "state"].iloc[0])
        if int(segment_count.get(state, 0)) < 2:
            # 该状态只有这一个区间，留一后训练集里就没有这个类，折无意义。
            continue
        test_ids = meta.loc[mask, "window_id"].to_numpy()
        if test_ids.size < min_test_windows:
            continue
        folds.append(
            {
                "segment": str(segment),
                "state": state,
                "train_ids": meta.loc[~mask, "window_id"].to_numpy(),
                "test_ids": test_ids,
                "test_windows": int(test_ids.size),
                "train_windows": int((~mask).sum()),
                "test_seconds": float(
                    (meta.loc[mask, "end_seconds"] - meta.loc[mask, "start_seconds"]).sum()
                ),
            }
        )
    return folds


def filter_rare_classes(
    meta: pd.DataFrame,
    min_windows: int = 12,
) -> tuple[list[str], dict[str, int]]:
    """丢掉纯窗口太少的类别：样本量不足以同时支撑训练与验证。"""
    counts = meta["state"].value_counts()
    keep = sorted(name for name, count in counts.items() if count >= min_windows)
    dropped = {str(name): int(count) for name, count in counts.items() if name not in keep}
    return keep, dropped


def check_no_overlap(
    windows: pd.DataFrame,
    train_ids: np.ndarray,
    test_ids: np.ndarray,
) -> dict[str, object]:
    """程序化校验：训练窗口与验证窗口在时间轴上没有任何重叠。"""
    index = windows.set_index("window_id")
    train = index.loc[train_ids, ["start_seconds", "end_seconds"]].to_numpy(dtype=float)
    test = index.loc[test_ids, ["start_seconds", "end_seconds"]].to_numpy(dtype=float)
    overlaps = 0
    for start, end in train:
        hits = np.sum((test[:, 0] < end - 1e-9) & (test[:, 1] > start + 1e-9))
        overlaps += int(hits)
    return {"overlapping_window_pairs": overlaps, "passed": overlaps == 0}


def _label_encode(y: pd.Series) -> tuple[np.ndarray, list[str]]:
    classes = sorted(y.unique().tolist())
    mapping = {name: index for index, name in enumerate(classes)}
    return y.map(mapping).to_numpy(dtype=int), classes


def train_xgboost(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_test: pd.DataFrame,
    y_test: np.ndarray,
    classes: list[str],
    seed: int = 20261012,
    n_estimators: int = 300,
    balanced: bool = True,
) -> tuple[object, dict[str, object], np.ndarray]:
    """训练 XGBoost 多分类器并返回模型、指标与混淆矩阵。

    `balanced=True` 时按类别频次倒数加权，避免步行段样本数压倒其它状态。
    """
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    from xgboost import XGBClassifier

    # XGBoost 不接受“中间缺类别”的标签（例如某折训练集里没有电梯），
    # 因此这里把出现过的标签重映射到紧凑的 0..m-1 空间。
    present = sorted({int(value) for value in np.concatenate([y_train, y_test])})
    remap = {value: index for index, value in enumerate(present)}
    names = [classes[value] for value in present]
    y_train = np.asarray([remap[int(value)] for value in y_train], dtype=int)
    y_test = np.asarray([remap[int(value)] for value in y_test], dtype=int)
    classes = names

    started = time.perf_counter()
    model = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.9,
        colsample_bytree=0.8,
        objective="multi:softprob",
        num_class=len(present),
        tree_method="hist",
        n_jobs=0,
        random_state=seed,
        eval_metric="mlogloss",
    )
    weights = None
    if balanced:
        counts = np.bincount(y_train, minlength=len(classes)).astype(float)
        counts[counts == 0] = 1.0
        weights = (len(y_train) / (len(classes) * counts))[y_train]
    model.fit(X_train.to_numpy(dtype=float), y_train, sample_weight=weights)
    train_seconds = time.perf_counter() - started

    predicted = model.predict(X_test.to_numpy(dtype=float))
    labels = list(range(len(classes)))
    report = classification_report(
        y_test, predicted, labels=labels, target_names=classes, output_dict=True, zero_division=0
    )
    matrix = confusion_matrix(y_test, predicted, labels=labels)
    metrics = {
        "accuracy": float(accuracy_score(y_test, predicted)),
        "macro_f1": float(report["macro avg"]["f1-score"]),
        "weighted_f1": float(report["weighted avg"]["f1-score"]),
        "per_class": {
            name: {
                "precision": float(report[name]["precision"]),
                "recall": float(report[name]["recall"]),
                "f1": float(report[name]["f1-score"]),
                "support": int(report[name]["support"]),
            }
            for name in classes
        },
        "train_seconds": round(train_seconds, 2),
        "balanced_sample_weight": bool(balanced),
        "train_rows": int(X_train.shape[0]),
        "test_rows": int(X_test.shape[0]),
        "dimension": int(X_train.shape[1]),
        "xgboost_version": _module_version("xgboost"),
    }
    return model, metrics, matrix


def shap_ranking(
    model: object,
    X: pd.DataFrame,
    classes: list[str],
    max_rows: int = 200,
    seed: int = 20261012,
) -> tuple[pd.Series, dict[str, object]]:
    """用 SHAP 给出每个特征对所有类别的平均绝对贡献。"""
    import shap

    started = time.perf_counter()
    sample = X if len(X) <= max_rows else X.sample(max_rows, random_state=seed)
    explainer = shap.TreeExplainer(model)
    values = explainer.shap_values(sample.to_numpy(dtype=float))
    if isinstance(values, list):
        stacked = np.mean([np.abs(np.asarray(item)) for item in values], axis=0)
    else:
        array = np.asarray(values)
        stacked = np.abs(array).mean(axis=-1) if array.ndim == 3 else np.abs(array)
    importance = pd.Series(stacked.mean(axis=0), index=sample.columns).sort_values(ascending=False)
    meta = {
        "rows_explained": int(sample.shape[0]),
        "seconds": round(time.perf_counter() - started, 2),
        "shap_version": _module_version("shap"),
        "classes": classes,
    }
    return importance, meta


def _family_table(importance: pd.Series, top_k: int) -> pd.DataFrame:
    frame = importance.rename("shap_mean_abs").to_frame()
    frame["family"] = [feature_family(name) for name in frame.index]
    frame["rank"] = np.arange(1, len(frame) + 1)
    frame["in_top_k"] = frame["rank"] <= top_k
    return frame


def run_advanced_experiment(
    session_dir: str | Path,
    out_dir: str | Path | None = None,
    window_seconds: float = 4.0,
    step_seconds: float = 2.0,
    channels: tuple[str, ...] = DEFAULT_CHANNELS,
    fc_parameters: str = "efficient",
    top_k: int = 20,
    test_fraction: float = 0.3,
    n_estimators: int = 300,
    shap_rows: int = 200,
    min_class_windows: int = 8,
    min_test_windows: int = 3,
    seed: int = 20261012,
    reuse_features: bool = False,
    separate_stairs: bool = False,
    out_suffix: str = "",
) -> Path:
    session = load_session(session_dir)
    output = (Path(out_dir) if out_dir else Path("analysis_outputs") / session.session_id) / (
        f"advanced{out_suffix}"
    )
    output = output.resolve()
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    spec = WindowSpec(window_seconds=window_seconds, step_seconds=step_seconds)
    total_windows = len(iter_window_bounds(session.duration_seconds, spec))
    aliases = SEPARATE_STAIRS_ALIASES if separate_stairs else None
    meta_all = build_pure_windows(session, spec, aliases=aliases)

    keep_states, dropped_states = filter_rare_classes(meta_all, min_windows=min_class_windows)
    meta = meta_all[meta_all["state"].isin(keep_states)].reset_index(drop=True)

    # 特征矩阵按“全部纯窗口”提取并缓存：类别筛选（例如静止样本太少）与
    # 上下楼梯是否拆分都不影响窗口集合，因此同一份缓存可以被不同配置复用。
    cache_path = output / "advanced_tsfresh_features.csv.gz"
    needed = set(int(value) for value in meta_all["window_id"])
    features: pd.DataFrame | None = None
    if reuse_features and cache_path.exists():
        cached = pd.read_csv(cache_path, index_col=0)
        cached_ids = {int(value) for value in cached.index}
        if needed.issubset(cached_ids):
            features = cached
            extract_meta = {
                "source": "cache",
                "cache": str(cache_path),
                "rows": int(cached.shape[0]),
                "raw_dimension": int(cached.shape[1]),
                "sha256": _sha256(cache_path),
            }
        else:
            print(
                f"缓存缺少 {len(needed - cached_ids)} 个窗口的自动特征，重新提取（缓存已按全部纯窗口重算）"
            )

    if features is None:
        long_table = build_long_table(session, meta_all, channels=channels)
        features, extract_meta = extract_tsfresh_features(long_table, fc_parameters=fc_parameters)
        features.index.name = "window_id"
        features.to_csv(cache_path, compression="gzip", encoding="utf-8")
        extract_meta["cache"] = str(cache_path)
        extract_meta["sha256"] = _sha256(cache_path)

    # 再按本次配置的类别筛选窗口
    features = features.loc[[value for value in features.index if int(value) in needed]]
    matrix, clean_report = clean_feature_matrix(features)

    # TSFresh 输出的索引没有名字，这里显式对齐回 window_id，避免 reset_index 变成 "index" 列。
    matrix = matrix.loc[[value for value in matrix.index if int(value) in set(meta["window_id"])]]
    meta = meta.set_index("window_id").loc[matrix.index]
    meta.index.name = "window_id"
    meta = meta.reset_index()
    y_text = meta["state"]
    y_encoded, classes = _label_encode(y_text)
    y_array = pd.Series(y_encoded, index=matrix.index)

    train_ids, test_ids, split_report = split_windows(
        meta,
        window_seconds=window_seconds,
        step_seconds=step_seconds,
        test_fraction=test_fraction,
    )
    split_report["test_fraction_requested"] = test_fraction
    leakage = check_no_overlap(meta, train_ids, test_ids)

    train_index = matrix.index.intersection(train_ids)
    test_index = matrix.index.intersection(test_ids)
    X_train, X_test = matrix.loc[train_index], matrix.loc[test_index]
    y_train = y_array.loc[train_index].to_numpy()
    y_test = y_array.loc[test_index].to_numpy()

    model, auto_metrics, confusion = train_xgboost(
        X_train, y_train, X_test, y_test, classes, seed=seed, n_estimators=n_estimators
    )
    gain_importance = pd.Series(model.feature_importances_, index=matrix.columns).sort_values(
        ascending=False
    )
    shap_importance, shap_meta = shap_ranking(model, X_test, classes, max_rows=shap_rows, seed=seed)
    family = _family_table(shap_importance, top_k=top_k)
    top_features = shap_importance.head(top_k).index.tolist()

    light_model, light_metrics, light_confusion = train_xgboost(
        X_train[top_features],
        y_train,
        X_test[top_features],
        y_test,
        classes,
        seed=seed,
        n_estimators=n_estimators,
    )

    handcrafted = _handcrafted_matrix(output.parent / "window_features.csv", meta["window_id"])
    hand_train = handcrafted.loc[handcrafted.index.intersection(train_ids)]
    hand_test = handcrafted.loc[handcrafted.index.intersection(test_ids)]
    _, hand_metrics, hand_confusion = train_xgboost(
        hand_train,
        y_array.loc[hand_train.index].to_numpy(),
        hand_test,
        y_array.loc[hand_test.index].to_numpy(),
        classes,
        seed=seed,
        n_estimators=n_estimators,
    )

    folds = leave_one_segment_out(meta, min_test_windows=min_test_windows)
    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        fold_train = matrix.index.intersection(fold["train_ids"])
        fold_test = matrix.index.intersection(fold["test_ids"])
        if fold_train.empty or fold_test.empty:
            continue
        _, fold_metrics, _ = train_xgboost(
            matrix.loc[fold_train],
            y_array.loc[fold_train].to_numpy(),
            matrix.loc[fold_test],
            y_array.loc[fold_test].to_numpy(),
            classes,
            seed=seed,
            n_estimators=n_estimators,
        )
        held_out = str(fold["state"])
        fold_rows.append(
            {
                "held_out_segment": fold["segment"],
                "held_out_state": held_out,
                "test_windows": fold["test_windows"],
                "test_seconds": fold["test_seconds"],
                "accuracy": fold_metrics["accuracy"],
                "macro_f1": fold_metrics["macro_f1"],
                "held_out_recall": fold_metrics["per_class"][held_out]["recall"],
                "held_out_f1": fold_metrics["per_class"][held_out]["f1"],
            }
        )
    fold_frame = pd.DataFrame(fold_rows)

    comparison = pd.DataFrame(
        [
            {
                "特征集": "手工四件套 + 频域",
                "dimension": int(handcrafted.shape[1]),
                "macro_f1": hand_metrics["macro_f1"],
                "accuracy": hand_metrics["accuracy"],
                "train_seconds": hand_metrics["train_seconds"],
            },
            {
                "特征集": "TSFresh 全特征",
                "dimension": int(matrix.shape[1]),
                "macro_f1": auto_metrics["macro_f1"],
                "accuracy": auto_metrics["accuracy"],
                "train_seconds": auto_metrics["train_seconds"],
            },
            {
                "特征集": f"TSFresh top-{top_k}（SHAP 筛选）",
                "dimension": int(light_metrics["dimension"]),
                "macro_f1": light_metrics["macro_f1"],
                "accuracy": light_metrics["accuracy"],
                "train_seconds": light_metrics["train_seconds"],
            },
        ]
    )

    summary = {
        "session_id": session.session_id,
        "window_seconds": window_seconds,
        "step_seconds": step_seconds,
        "channels": list(channels),
        "windows_total": int(total_windows),
        "windows_pure": int(len(meta_all)),
        "windows_used": int(len(meta)),
        "windows_dropped_non_pure": int(total_windows - len(meta_all)),
        "stairs_as_separate_classes": bool(separate_stairs),
        "classes_dropped_too_few_windows": dropped_states,
        "state_windows": {str(k): int(v) for k, v in y_text.value_counts().items()},
        "extract": extract_meta,
        "clean": clean_report,
        "split": split_report,
        "leakage_check": leakage,
        "classes": classes,
        "auto_metrics": auto_metrics,
        "light_metrics": light_metrics,
        "handcrafted_metrics": hand_metrics,
        "shap": shap_meta,
        "top_k": top_k,
        "top_features": top_features,
        "top_feature_families": {
            str(k): int(v) for k, v in family[family["in_top_k"]]["family"].value_counts().items()
        },
        "family_share_all_features": {
            str(k): float(v) for k, v in family["family"].value_counts(normalize=True).items()
        },
        "leave_one_segment_out": fold_rows,
        "figures": {},
    }

    summary["figures"]["comparison"] = str(
        plot_advanced_comparison(comparison, figures / "advanced_model_comparison.png")
    )
    summary["figures"]["confusion"] = str(
        plot_advanced_confusion(confusion, classes, figures / "advanced_confusion.png")
    )
    summary["figures"]["shap"] = str(
        plot_advanced_shap(shap_importance.head(top_k), figures / "advanced_shap_topk.png")
    )

    comparison.to_csv(output / "advanced_model_comparison.csv", index=False, encoding="utf-8-sig")
    family.head(150).to_csv(output / "advanced_feature_ranking.csv", encoding="utf-8-sig")
    gain_importance.rename("gain_importance").to_frame().to_csv(
        output / "advanced_gain_importance.csv", encoding="utf-8-sig"
    )
    pd.DataFrame(confusion, index=classes, columns=classes).to_csv(
        output / "advanced_confusion_matrix.csv", encoding="utf-8-sig"
    )
    pd.DataFrame(light_confusion, index=classes, columns=classes).to_csv(
        output / "advanced_confusion_matrix_topk.csv", encoding="utf-8-sig"
    )
    if not fold_frame.empty:
        fold_frame.to_csv(output / "advanced_fold_generalization.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "window_id": X_test.index,
            "state": [classes[int(value)] for value in y_test],
            "predicted": [
                classes[int(value)] for value in light_model.predict(X_test[top_features].to_numpy(dtype=float))
            ],
            "start_seconds": meta.set_index("window_id").loc[X_test.index, "start_seconds"].to_numpy(),
            "segment_id": meta.set_index("window_id").loc[X_test.index, "segment_id"].to_numpy(),
        }
    ).to_csv(output / "advanced_test_predictions.csv", index=False, encoding="utf-8-sig")
    X_test[top_features].to_csv(output / "advanced_topk_features.csv", encoding="utf-8-sig")
    (output / "advanced_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return output


def _handcrafted_matrix(source: Path, window_ids: pd.Series) -> pd.DataFrame:
    """从已有的逐窗口特征表里取出“手工特征”子集，用于对比。"""
    if not Path(source).exists():
        raise FileNotFoundError(
            f"找不到 {source}，请先运行 python -m sensor_analysis.pipeline 生成逐窗口特征表"
        )
    frame = pd.read_csv(source)
    columns = [
        name
        for name in frame.columns
        if name.startswith(HANDCRAFTED_PREFIXES) or name in HANDCRAFTED_COLUMNS
    ]
    selected = frame.set_index("window_id").loc[window_ids.tolist(), columns]
    return selected.astype(float)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TSFresh + XGBoost 进阶流水线")
    parser.add_argument("--session", required=True, help="会话目录（含 accelerometer.csv 等）")
    parser.add_argument("--out", default=None, help="输出目录，默认 analysis_outputs/<session_id>")
    parser.add_argument("--window", type=float, default=4.0, help="窗长（秒）")
    parser.add_argument("--step", type=float, default=2.0, help="步进（秒）")
    parser.add_argument("--channels", default="accel", choices=["accel", "accel+gyro"], help="参与自动特征提取的通道")
    parser.add_argument("--fc", default="efficient", choices=["efficient", "minimal"], help="TSFresh 特征参数集")
    parser.add_argument("--top-k", type=int, default=20, help="SHAP 筛选后保留的特征数")
    parser.add_argument("--test-fraction", type=float, default=0.3, help="验证集比例")
    parser.add_argument("--n-estimators", type=int, default=300, help="XGBoost 树数量")
    parser.add_argument("--shap-rows", type=int, default=200, help="计算 SHAP 的样本上限")
    parser.add_argument("--seed", type=int, default=20261012, help="随机种子")
    parser.add_argument(
        "--stairs-separate",
        action="store_true",
        help="把上楼梯 / 下楼梯当成两个独立状态（默认都归为楼梯）",
    )
    parser.add_argument(
        "--out-suffix",
        default="",
        help="在 advanced 目录后追加后缀，便于把不同配置的结果分开保存",
    )
    parser.add_argument(
        "--reuse-features",
        action="store_true",
        help="复用已缓存的 TSFresh 特征矩阵（advanced_tsfresh_features.csv.gz），跳过约 7 分钟的提取",
    )
    args = parser.parse_args(argv)

    channels = DEFAULT_CHANNELS if args.channels == "accel" else DEFAULT_CHANNELS + GYRO_CHANNELS
    output = run_advanced_experiment(
        session_dir=args.session,
        out_dir=args.out,
        window_seconds=args.window,
        step_seconds=args.step,
        channels=tuple(channels),
        fc_parameters=args.fc,
        top_k=args.top_k,
        test_fraction=args.test_fraction,
        n_estimators=args.n_estimators,
        shap_rows=args.shap_rows,
        seed=args.seed,
        reuse_features=args.reuse_features,
        separate_stairs=args.stairs_separate,
        out_suffix=args.out_suffix,
    )
    print(f"进阶分析完成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
