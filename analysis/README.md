# sensor-analysis · 第 2 课时特征工程分析工程

对 Android 采集器导出的会话目录做**只读**分析：质量检查、标签解析、滑动窗口、手写时域四件套、
FFT 主峰步频、D06 参数实验场、D07 混叠实验、公交防误计步特征，并生成图表与报告。

原始 `accelerometer.csv` / `gyroscope.csv` **不覆盖、不修改**；所有重采样、去均值、滤波都只在内存或派生输出中进行。

## 目录结构

```text
analysis/
├── pyproject.toml
├── README.md
├── src/sensor_analysis/
│   ├── session.py          # 读取 CSV / metadata.json / labels.csv
│   ├── quality.py          # 时间戳、间断、单位量级与标签映射检查
│   ├── windows.py          # 滑窗与标签区间解析
│   ├── features_time.py    # 均值 / 方差 / 过零率 / 峰值
│   ├── features_freq.py    # FFT、主峰、步频、频带能量、峰间隔
│   ├── experiment_d06.py   # 窗长 / 步进参数实验场
│   ├── experiment_d07.py   # 混叠实验
│   ├── bus_false_step.py   # 公交防误计步两个特征
│   ├── plotting.py         # 所有图表
│   └── pipeline.py         # 一键管道（命令行入口）
└── tests/
    ├── test_time_features.py
    └── test_frequency_features.py
```

## 环境与安装

```bash
cd analysis
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

依赖：`numpy`、`pandas`、`matplotlib`、`scipy`，测试使用 `pytest`。

## 一键运行

```bash
# 仓库根目录执行
python -m sensor_analysis.pipeline --session data/task3/raw --out analysis_outputs/20261008_195431_052
```

也可以安装后使用脚本入口：

```bash
cd analysis && pip install -e .
sensor-analysis --session ../data/task3/raw --window 4 --step 2 --band-low 0.5 --band-high 3.0
```

## 输出文件

```text
analysis_outputs/<session_id>/
├── quality_report.json
├── labels_resolved.csv
├── windows.csv
├── window_features.csv            # 时域四件套 + 频域特征合并表
├── window_frequency_features.csv
├── spectrum.npz
├── d06_summary.json / d06_window_sweep.csv / d06_event_split.csv
├── d07_summary.json
├── bus_summary.json
├── figures/
│   ├── waveform.png
│   ├── time_features.png
│   ├── fft_spectrum.png
│   ├── time_frequency.png
│   ├── d06_window_sweep.png
│   ├── d07_alias.png
│   └── bus_features.png
└── report.md
```

## 关键约定

- 方差采用**总体方差** `ddof=0`；
- 峰值采用去均值后的**动态峰值** `max|x-mean|`，同时保留 `peak_raw`；
- 过零率 = 去均值信号过零次数 / 时长，可选 FFT 带限；
- 频率分辨率 `Δf = fs / N = 1 / W`；
- 步频 `step_frequency_spm = f_peak × 60`；
- 主峰在行人步频带 `0.5 ~ 3 Hz` 内查找。

## 测试

```bash
cd analysis
pytest
```
