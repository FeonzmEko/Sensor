# 真机安装与调试报告

> 设备：Xiaomi 25019PNF3C（Xiaomi 15 Ultra，`xuanyuan`），Android 17 / SDK 37
> 序列号：`a1d42191`
> 调试日期：2026-10-11
> 工具链：adb `C:\Users\Qingfeng\AppData\Local\Android\Sdk\platform-tools\adb.exe`、Gradle 9.6.0 + JDK 25

---

## 1. 安装与启动

| 步骤 | 命令 | 结果 |
|---|---|---|
| 连接设备 | `adb kill-server && adb start-server && adb devices -l` | `a1d42191 device product:xuanyuan model:25019PNF3C` |
| 安装 Debug APK | `adb install -r app/build/outputs/apk/debug/app-debug.apk` | `Success` |
| 启动应用 | `adb shell am start -n com.example.sensorlog/.MainActivity` | 正常进入主界面，无崩溃 |
| 日志检查 | `adb logcat` | 无 `AndroidRuntime` / `FATAL` |

安装后确认应用完整显示新界面：采集配置表单（路线名称、手机位置、手机朝向、备注、目标时长）、
开始/停止采集、事件下拉 + 自定义标签 + 打点按钮、采集状态区、传感器型号与实时波形。

---

## 2. MIUI / HyperOS 限制

真机上发现两个系统级限制，均已在调试中绕过或规避：

1. **`adb shell input` 被禁用**
   - 现象：`java.lang.SecurityException: Injecting input events requires ... INJECT_EVENTS permission`。
   - 影响：无法用 `adb shell input tap/text/keyevent` 脚本化点击界面。
   - 规避：改用**真机仪器化测试（AndroidJUnitRunner）**直接驱动 `SensorSessionRecorder`，不依赖输入注入。

2. **AGP 自动安装测试 APK 失败**
   - 现象：`SecurityException: You need the android.permission.INSTALL_GRANT_RUNTIME_PERMISSIONS permission`，
     且 Gradle 测试任务会先卸载主 APK。
   - 规避：手动 `adb install -r -t` 安装测试 APK，再用 `adb shell am instrument` 运行；
     运行前需重新安装主 APK。

---

## 3. 真机冒烟会话 A：约 6 秒

- 会话：`20261011_093554_273`，目标时长 5 s，实际 6.0 s
- 结果：**测试通过**（`OK (1 test)`，耗时 6.056 s）
- 采样：加速度计 691 点 / 115.04 Hz；陀螺仪 276 点 / 46.02 Hz
- 标签：`开始步行`、`到达`（2 次）
- 元数据：`schema_version=2`、`status=completed`、`app_version=1.0`、路线/位置/朝向/目标时长齐全
- 数据归档：`data/lesson2/20261011_093554_273/`

该会话验证了：会话配置写入、`labels.csv` 表头与内容、`metadata.json` 扩展字段、
停止后 `completed` 状态、原始 CSV 表头与精度。

---

## 4. 真机冒烟会话 B：约 2 分钟（任务清单第 6 步）

- 会话：`20261011_093758_739`，目标时长 120 s，实际 142 s
- 结果：**测试通过**（`OK (1 test)`，耗时 142.056 s）
- 采样：加速度计 13664 点；陀螺仪 5464 点
- 标签：`开始步行`、`上车`、`下车`、`到达`（4 次）
- 元数据：`status=completed`，`route_name=instrumented-2min-smoke`，`target_duration_seconds=120`
- 数据归档：`data/lesson2/20261011_093758_739/`

### 4.1 发现的真实问题：后台运行会被系统冻结

质量检查（`analysis_outputs/20261011_093758_739/quality_report.json`）：

| 检查项 | 加速度计 | 陀螺仪 |
|---|---:|---:|
| 时间戳严格递增 | 是 | 是 |
| 重复 / 回退时间戳 | 0 / 0 | 0 / 0 |
| 超过 100 ms 间断 | **1** | **1** |
| 最大相邻间隔 | **22.18 s** | **22.24 s** |
| 实测频率 | 96.94 Hz | 38.76 Hz |

**原因**：该会话由仪器化测试驱动，没有前台 Activity、没有 `FLAG_KEEP_SCREEN_ON`。
设备熄屏后进入省电/冻结状态，MIUI 暂停了应用进程约 22 秒，非唤醒型传感器随之停采，
导致两个 CSV 都出现一个 22 秒长间断，实测频率被拉低。

**结论与对应措施**：

- 正式采集必须保持 **MainActivity 在前台 + 屏幕常亮**（应用已实现 `FLAG_KEEP_SCREEN_ON` 与
  `onPause()` 自动停止），这正是任务清单第 8 节的要求；
- 长间断检测（`gaps_over_100ms`）必须作为正式数据的准入条件，本次该会话被正确判为
  `overall_pass = false`，说明质量检查脚本能识别真实的采集中断；
- 不要用后台/锁屏方式做正式 20 分钟采集。

### 4.2 标签到样本的映射

`labels_resolved.csv` 与 `windows.csv` 显示 4 个事件全部匹配到最近的加速度计样本，
最大偏移 **3.45 ms**；窗口状态被正确解析为
`unknown → 开始步行 → 上车 → 下车 → 到达`，验证了“相邻事件之间继承前一个状态”的规则。

---

## 5. 调试中发现并修复的软件缺陷

真机 2 分钟会话（窗口 `W=2 s`）触发了公交防误计步模块的崩溃：

```
ValueError: operands could not be broadcast together with shapes (59,) (58,)
```

**根因**：`bus_false_step.py` 对能量占比 R 和变异系数 CV 分别用 `_clean()` 剔除 `NaN`，
当某个窗口的 CV 为 `NaN` 时两个数组长度不再一致。

**修复**：新增 `_clean_pair()`，对 R 与 CV 做联合掩码清洗，保证一一对应；
并补充回归测试 `analysis/tests/test_bus_features.py`（含 2 秒短窗场景）。

**验证**：`pytest` 13 项全部通过，两个会话的完整分析管道均重新跑通。

---

## 6. 复现命令

```bash
# 构建
gradlew :app:assembleDebug :app:assembleDebugAndroidTest

# 手动安装（绕开 MIUI 对 -g 的限制）
adb -s a1d42191 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s a1d42191 install -r -t app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk

# 6 秒冒烟
adb -s a1d42191 shell am instrument -w -e class \
  com.example.sensorlog.SensorSessionRecorderDeviceTest#recordsRealSensorDataWithLabelsAndMetadata \
  com.example.sensorlog.test/androidx.test.runner.AndroidJUnitRunner

# 2 分钟带标签冒烟
adb -s a1d42191 shell am instrument -w -e class \
  com.example.sensorlog.SensorSessionRecorderDeviceTest#recordsTwoMinuteLabelledSmokeSession \
  com.example.sensorlog.test/androidx.test.runner.AndroidJUnitRunner

# 拉取会话
adb -s a1d42191 pull \
  /storage/emulated/0/Android/data/com.example.sensorlog/files/sensor-sessions/<session_id> \
  data/lesson2/<session_id>

# 分析
python -m sensor_analysis.pipeline --session data/lesson2/<session_id> \
  --out analysis_outputs/<session_id> --window 4 --step 2
```

---

## 7. 真机调试结论

- 应用可在真机正常安装、启动、读取传感器并显示波形，无崩溃；
- 会话配置、`labels.csv` 打点、`metadata.json` 扩展、`completed` 状态、原始 CSV 精度全部验证通过；
- 事件标签与传感器样本时间可精确对齐（最大偏移 3.45 ms）；
- 发现并修复了一个真实的 Python 分析缺陷；
- 发现“后台/锁屏运行会导致约 22 秒采集中断”，确认正式采集必须前台常亮，且质量检查能识别该类中断。
