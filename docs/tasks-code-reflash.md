# 第 2 课时 · 工程代码刷新任务清单

> 依据：《多元感知融合 · 第 2 课时 特征工程》以及当前仓库的实际状态整理。
>
> 本文件只记录工程改造计划与验收项，不修改 Kotlin、Gradle、XML 或 Python 代码。实际执行时再按本清单逐项改动。
>
> 核心原则：Android App 只负责稳定采集和打标签，PC 端 Python 工程负责质量检查、滑窗、时域特征、频域特征、实验和报告。

## 1. 当前代码与数据基线

- [x] 现有 App 可同步注册加速度计与陀螺仪。
- [x] 现有 App 保留原始 `SensorEvent.timestamp`。
- [x] 每次采集可生成独立会话目录。
- [x] 当前会输出 `accelerometer.csv`、`gyroscope.csv` 和 `metadata.json`。
- [x] 已完成 62.5 秒短测和 571.3 秒匀速步行采集。
- [x] 571.3 秒数据可作为算法调试和 FFT 链路验证样本。
- [ ] 571.3 秒数据不能替代第 2 次课要求的约 20 分钟混合状态数据。
- [ ] 当前数据未记录明确路线、持握方式、朝向和事件标签。
- [ ] 当前仓库没有独立的 Python 特征工程分析工程。
- [ ] 当前仓库没有窗口级特征表、FFT 结果、D06/D07 记录和公交误计步分析。

### 1.1 当前数据适用范围

| 数据 | 状态 | 可否用于第 2 次课最终提交 |
|---|---|---|
| `docs/evidence/task3-short-test` | 62.5 秒短测 | 否，仅用于冒烟验证 |
| `data/task3` | 571.3 秒手持匀速步行 | 可作为调试样本，不能作为最终 20 分钟主数据 |
| 新的 20 分钟日常路线数据 | 尚未采集 | 是，最终报告应主要使用该数据 |

## 2. 最终工程结构

```text
Sensor/
├── app/                         # Android 采集器，继续保留
│   └── src/main/
│       ├── java/com/example/sensorlog/
│       │   ├── MainActivity.kt
│       │   ├── SensorSessionRecorder.kt
│       │   ├── WaveformView.kt
│       │   └── HelloWorldActivity.kt
│       └── res/
├── data/                        # 原始数据、整理数据和备份
├── analysis/                    # 新增：Python 特征工程工程
│   ├── pyproject.toml
│   ├── README.md
│   ├── src/sensor_analysis/
│   └── tests/
├── analysis_outputs/            # 新增：质量报告、特征表、图表
├── docs/
│   ├── tasks.md
│   ├── tasks2.md
│   ├── tasks-code-reflash.md
│   └── experiment2-report.md    # 新增：最终实验报告
└── README.md
```

## 3. 现有文件处理清单

### 3.1 保留不改

- [ ] 保留 `app/src/main/java/com/example/sensorlog/WaveformView.kt`。
- [ ] 保留 `app/src/main/java/com/example/sensorlog/HelloWorldActivity.kt`。
- [ ] 保留 `app/src/main/res/layout/activity_hello_world.xml`。
- [ ] 保留 `app/src/main/AndroidManifest.xml` 的现有前台采集模式。
- [ ] 保留 `docs/tasks.md` 作为第 1 次课任务记录。
- [ ] 保留 `docs/task2-verification.md`、`docs/task3-short-test.md`、`docs/task3-verification.md`。
- [ ] 保留 `data/task3`，作为第 1 次课交付和 Python 冒烟测试输入。
- [ ] 保留原始 CSV，不覆盖、不修改、不在原文件上插值或滤波。

### 3.2 后续需要修改的工程文件

- [ ] `app/src/main/java/com/example/sensorlog/MainActivity.kt`
  - [ ] 增加采集配置读取。
  - [ ] 增加 20 分钟倒计时或已采集时长显示。
  - [ ] 增加事件打点入口。
  - [ ] 增加采集会话的运行状态和标签反馈。
  - [ ] 保留现有实时波形和 `onPause()` 停止逻辑。
- [ ] `app/src/main/java/com/example/sensorlog/SensorSessionRecorder.kt`
  - [ ] 增加 `SessionConfig` 或等价配置对象。
  - [ ] 增加 `route_name`、`device_placement`、`orientation` 元数据。
  - [ ] 增加 `app_version` 和 `target_duration_seconds` 元数据。
  - [ ] 增加 `labels.csv` 写入能力。
  - [ ] 增加 `markEvent(label)` 或等价事件记录接口。
  - [ ] 保持原始传感器 CSV 的列名和精度。
- [ ] `app/src/main/res/layout/activity_main.xml`
  - [ ] 增加路线名称输入。
  - [ ] 增加手机位置和朝向输入。
  - [ ] 增加事件打点按钮。
  - [ ] 增加采集时长和事件状态显示。
- [ ] `app/src/main/res/values/strings.xml`
  - [ ] 增加新增控件对应的字符串资源。
- [ ] `.gitignore`
  - [ ] 忽略 Python 虚拟环境。
  - [ ] 忽略原始数据、派生结果、缓存和临时文件。
  - [ ] 不忽略最终报告、关键图表和必要的校验文件。
- [ ] `README.md`
  - [ ] 增加 Python 分析工程的运行方法。
  - [ ] 增加 20 分钟数据采集协议。
  - [ ] 增加最终输出目录说明。

### 3.3 后续需要新增的文件

- [ ] `analysis/pyproject.toml`
- [ ] `analysis/README.md`
- [ ] `analysis/src/sensor_analysis/__init__.py`
- [ ] `analysis/src/sensor_analysis/session.py`
- [ ] `analysis/src/sensor_analysis/quality.py`
- [ ] `analysis/src/sensor_analysis/windows.py`
- [ ] `analysis/src/sensor_analysis/features_time.py`
- [ ] `analysis/src/sensor_analysis/features_freq.py`
- [ ] `analysis/src/sensor_analysis/experiment_d06.py`
- [ ] `analysis/src/sensor_analysis/experiment_d07.py`
- [ ] `analysis/src/sensor_analysis/bus_false_step.py`
- [ ] `analysis/src/sensor_analysis/pipeline.py`
- [ ] `analysis/src/sensor_analysis/plotting.py`
- [ ] `analysis/tests/test_time_features.py`
- [ ] `analysis/tests/test_frequency_features.py`
- [ ] `docs/experiment2-report.md`

### 3.4 可删除或清理的内容

- [ ] 删除根目录 0 字节误生成文件 `当前状态：2026-10-08`。
- [ ] 删除根目录 0 字节误生成文件 `当前状态：双传感器同步采集器已实现，并完成`。
- [ ] 可选：删除未使用的 `navigation-fragment-ktx` 依赖。
- [ ] 可选：删除未使用的 `navigation-ui-ktx` 依赖。
- [ ] 不要删除波形、Hello World、采集器或已有真机证据。
- [ ] 不要删除 `data/task3` 原始数据目录。

## 4. Android 采集端改造任务

### 4.1 会话配置

- [ ] 开始采集前要求填写或选择路线名称。
- [ ] 开始采集前要求填写或选择手机位置。
- [ ] 开始采集前要求填写或选择手机朝向。
- [ ] 开始采集时记录目标时长，默认 `1200` 秒。
- [ ] 允许备注手机是否在兜里、手持、腰包或车内支架等。

### 4.2 元数据扩展

- [ ] 在 `metadata.json` 中增加 `experiment` 字段。
- [ ] 在 `metadata.json` 中增加 `app_version` 字段。
- [ ] 在 `metadata.json` 中增加 `route_name` 字段。
- [ ] 在 `metadata.json` 中增加 `device_placement` 字段。
- [ ] 在 `metadata.json` 中增加 `orientation` 字段。
- [ ] 在 `metadata.json` 中增加 `target_duration_seconds` 字段。
- [ ] 保留现有设备、传感器、样本统计、开始时间和结束时间字段。
- [ ] 确认停止后最终元数据状态为 `completed`，异常时记录错误。

### 4.3 事件标签

- [ ] 新增 `labels.csv`。
- [ ] 表头使用 `timestamp_elapsed_ns,wall_time_epoch_ms,label`。
- [ ] 点击“打点”时记录 `SystemClock.elapsedRealtimeNanos()`。
- [ ] 同时记录对应的墙钟时间。
- [ ] 支持记录“上车”“下车”“开始步行”“进入电梯”“到达”等标签。
- [ ] 支持重复标签或自定义标签时保留输入内容。
- [ ] 分析阶段能够按标签时间匹配最近的传感器样本。

### 4.4 采集运行状态

- [ ] 开始后显示已采集时长。
- [ ] 显示加速度计和陀螺仪当前样本数。
- [ ] 显示当前是否达到 20 分钟目标。
- [ ] 页面进入后台时仍然执行停止、flush、close 和元数据写入。
- [ ] 采集期间保持屏幕常亮。
- [ ] 不在本次任务中加入后台服务或长时间后台采集。

## 5. Python 分析工程任务

### 5.1 数据读取与质量检查

- [ ] 读取加计 CSV、陀螺 CSV、`metadata.json` 和 `labels.csv`。
- [ ] 校验 CSV 表头。
- [ ] 统计样本数、首末时间戳和有效时长。
- [ ] 按 `(样本数 - 1) / (末时间戳 - 首时间戳)` 计算实测频率。
- [ ] 检查时间戳严格单调递增。
- [ ] 统计重复时间戳和回退时间戳。
- [ ] 统计相邻间隔中位数、P95、P99 和最大值。
- [ ] 标记超过中位数 2 倍、3 倍和超过 100 ms 的间断。
- [ ] 检查加计单位量级和静止合矢量。
- [ ] 检查陀螺仪单位量级、范围和饱和风险。
- [ ] 输出 `quality_report.json`。

### 5.2 标签解析

- [ ] 根据 `labels.csv` 生成状态时间区间。
- [ ] 允许两个相邻事件之间的数据继承前一个状态。
- [ ] 对未标注区间标记为 `unknown`。
- [ ] 输出 `labels_resolved.csv`，记录每段起止时间和状态。
- [ ] 区分“原始标签”和“根据时间推断的标签”。

### 5.3 滑动窗口

- [ ] 支持窗长 `W` 配置。
- [ ] 支持步进 `S` 配置。
- [ ] 支持重叠率计算。
- [ ] 首选参数使用 2～4 秒窗长和 50% 重叠。
- [ ] 每个窗口保留会话编号、窗口序号、起止时间、起止样本索引和状态标签。
- [ ] 对采样不均匀的数据只建立派生重采样序列，不修改原始 CSV。
- [ ] 输出 `windows.csv`。

### 5.4 时域四件套

- [ ] 手写计算每窗均值 `mean`。
- [ ] 手写计算每窗方差 `var`。
- [ ] 手写计算去均值后的过零率 `ZCR`。
- [ ] 手写计算每窗峰值 `peak`。
- [ ] 明确方差采用总体方差或样本方差中的哪一种。
- [ ] 明确峰值采用原始合矢量、去均值合矢量或去重力动态幅值中的哪一种。
- [ ] 对 ZCR 增加带限处理选项。
- [ ] 对每个窗口分别输出三轴特征和必要的合矢量特征。
- [ ] 输出 `window_features.csv`。
- [ ] 用静止、慢走、快走段验证四件套分工。
- [ ] 生成时域特征对比图。
- [ ] 生成“动没动、动多快、动多大”的敏感度矩阵。

### 5.5 FFT 与步频

- [ ] 对每个窗口去除直流分量。
- [ ] 可选加入汉宁窗。
- [ ] 对非均匀时间戳的数据先生成等间隔派生信号。
- [ ] 计算单边频谱并在 `0～fs/2` 范围内查找主峰。
- [ ] 根据 `Δf = fs / N = 1 / W` 解释分辨率。
- [ ] 输出 `f_peak` 和 `step_frequency_spm = f_peak × 60`。
- [ ] 对比 FFT 主峰频率与峰间距法步频。
- [ ] 检查主峰是否落在行人步频带 `0.5～3 Hz`。
- [ ] 至少输出一段慢走和一段快走的时域/频域双联图。
- [ ] 输出频谱数据或缓存文件。
- [ ] 输出 `fft_spectrum.png` 和 `time_frequency.png`。

## 6. D06/D07 实验任务

### 6.1 D06 参数实验场

- [ ] 使用同一段数据，固定其他条件，只调整窗长。
- [ ] 将窗长推到极短端，记录方差抖动和 ZCR 噪声问题。
- [ ] 将窗长推到极长端，记录方差钝化和峰值升高问题。
- [ ] 将步进设置为 `S = W`，记录事件跨缝被劈开的失效案例。
- [ ] 将步进设置为约 50% 重叠，验证短事件可被完整覆盖。
- [ ] 生成窗口参数与四件套变化的关系图。
- [ ] 逐题回答 D06 页面提问。
- [ ] 保存 D06 失效状态截图。
- [ ] 保存 D06 恢复工作点截图。
- [ ] 输出 `d06_window_sweep.png`。

### 6.2 D07 混叠实验

- [ ] 依次设置 `fs = 50、5、3、2 Hz`。
- [ ] 记录每一步主峰频率和频谱形态。
- [ ] 判断主峰从哪一步开始折返。
- [ ] 验证 `2.8 Hz` 信号在 `fs = 2 Hz` 时得到 `1.2 Hz` 假峰。
- [ ] 解释奈奎斯特频率与混叠关系。
- [ ] 按“现象 → 指标 → 谱 → 采样率”复现失效链。
- [ ] 逐题回答 D07 页面提问。
- [ ] 保存关键频率配置的截图。
- [ ] 输出 `d07_alias.png`。

## 7. 作业②：公交防误计步任务

- [ ] 从 20 分钟数据中选取步行段和乘车段。
- [ ] 计算步频带能量占比：`P(0.5～3 Hz) / P(0.5～10 Hz)`。
- [ ] 计算峰间隔变异系数：`std(步间隔) / mean(步间隔)`。
- [ ] 可选计算主峰频率连续窗口的稳定度。
- [ ] 可选计算陀螺仪旋转能量，辅助区分步行姿态变化和车辆振动。
- [ ] 分别绘制步行与乘车的特征分布。
- [ ] 给出两个最终特征的定义、阈值思路和验证结果。
- [ ] 说明为什么仅使用“加速度大”或“方差大”会造成误判。
- [ ] 输出 `bus_features.png` 和文字结论。

## 8. 20 分钟采集执行任务

- [ ] 确定连续路线，例如宿舍、食堂、教学楼或校外短路线。
- [ ] 路线中尽量包含步行、乘车、静止、电梯等状态。
- [ ] 采集前记录路线名称。
- [ ] 采集前记录手机位置。
- [ ] 采集前记录手机朝向。
- [ ] 点击开始后先保持静止 1～2 分钟。
- [ ] 连续步行至少 3～5 分钟。
- [ ] 尽量包含一段乘车或校园车数据，用于公交防误计步。
- [ ] 再次步行 3～5 分钟。
- [ ] 如条件允许，包含电梯或静止段。
- [ ] 采集总时长不少于 20 分钟。
- [ ] 全程保持页面在前台，不熄屏、不切换应用。
- [ ] 全程不改变手机位置和朝向。
- [ ] 途中使用“打点”按钮记录关键事件。
- [ ] 停止后检查 `accelerometer.csv`、`gyroscope.csv`、`metadata.json` 和 `labels.csv`。
- [ ] 导出会话目录并复核文件是否完整。
- [ ] 计算原始数据归档包和校验文件。
- [ ] 完成至少两处备份。

## 9. 推荐执行顺序

- [ ] 第 1 步：整理并提交当前未提交的文档和数据。
- [ ] 第 2 步：用 `data/task3` 的 571.3 秒数据先搭 Python 读取和质量检查。
- [ ] 第 3 步：在短测或 571.3 秒数据上跑通滑窗和时域四件套。
- [ ] 第 4 步：在 571.3 秒步行数据上跑通 FFT 和步频主峰。
- [ ] 第 5 步：完善 Android 采集元数据和事件打点。
- [ ] 第 6 步：用真机做 2～3 分钟带标签冒烟采集。
- [ ] 第 7 步：执行 20 分钟正式采集。
- [ ] 第 8 步：对正式数据运行完整分析管道。
- [ ] 第 9 步：完成 D06、D07 失效实验。
- [ ] 第 10 步：完成公交防误计步分析。
- [ ] 第 11 步：整理图表、代码、原始数据、截图和报告。
- [ ] 第 12 步：计算归档哈希并完成双备份。
- [ ] 第 13 步：更新 `docs/tasks2.md` 的完成状态。

## 10. 推荐输出文件

### 10.1 正式数据目录

```text
data/lesson2/<session_id>/
├── accelerometer.csv
├── gyroscope.csv
├── metadata.json
├── labels.csv
├── collection_notes.md
└── SHA256SUMS.txt
```

### 10.2 分析输出目录

```text
analysis_outputs/<session_id>/
├── quality_report.json
├── labels_resolved.csv
├── windows.csv
├── window_features.csv
├── spectrum.npz
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

## 11. 不允许或暂不执行的改动

- [ ] 不把 FFT 和特征选择逻辑直接写进 Android App。
- [ ] 不添加后台采集 Service。
- [ ] 不申请不必要的后台传感器权限。
- [ ] 不覆盖或修改原始 CSV。
- [ ] 不在采集阶段做滤波、插值、旋转或降采样。
- [ ] 不用 `SENSOR_DELAY_GAME` 的理论值代替实测频率。
- [ ] 不使用老师的锚数据冒充本人数据。
- [ ] 不把 571.3 秒匀速步行数据当作最终 20 分钟实验数据。
- [ ] 不用 TSFresh 替代需要手写的保底四件套。
- [ ] 不只在报告里贴图而不解释参数、公式和失效原因。

## 12. 最终验收清单

- [ ] 有一条本人采集、约 20 分钟、连续无中断的日常路线数据。
- [ ] 数据包含至少两种运动状态，最好包含步行和乘车。
- [ ] 原始加计和陀螺 CSV 保留原始时间戳。
- [ ] 元数据完整记录设备、传感器、路线、位置、朝向和采集时间。
- [ ] 事件标签能够映射到传感器样本时间。
- [ ] 质量检查报告通过时间戳、重复值和长时间间断检查。
- [ ] 滑窗参数和窗口级特征表完整。
- [ ] 四件套由明确的手写公式计算。
- [ ] FFT 主峰能够换算为步频。
- [ ] D06 有失效区截图、页面问题和答案。
- [ ] D07 有混叠频率截图、页面问题和答案。
- [ ] 公交防误计步给出两个可计算、可验证的特征。
- [ ] 报告写明方法、参数、结果、局限和数据来源。
- [ ] 原始数据、派生结果、代码、图表和报告均已归档。
- [ ] 归档包具有 SHA-256。
- [ ] 至少完成两处备份。
- [ ] `docs/tasks2.md` 的对应状态已更新。