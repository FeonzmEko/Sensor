# 任务3：双传感器构建与短测验证

- 验证日期：2026-09-27
- 真机：Xiaomi `25019PNF3C`（`ro.product.device=xuanyuan`），Android 17 / API 37
- 加速度计：`lsm6dsv Accelerometer Non-wakeup`（STMicro）
- 陀螺仪：`lsm6dsv Gyroscope Non-wakeup`（STMicro）
- 采样档位：两个传感器均使用 `SensorManager.SENSOR_DELAY_GAME`
- 会话：`20260927_205325_015`
- 采集开始：`2026-09-27 20:53:25.017 +0800`
- 采集结束：`2026-09-27 20:54:27.525 +0800`
- 停止原因：`Activity paused`，用于验证 `onPause()` 自动停止、flush 和关闭文件

## 构建结果

执行：

```text
clean testDebugUnitTest assembleDebug
```

结果：`BUILD SUCCESSFUL`，43 个任务执行成功。

- APK：`app/build/outputs/apk/debug/app-debug.apk`
- APK 大小：`7,662,702` 字节
- APK SHA-256：`24C38AA54F81D49874092CB7B558123D465A707A8AFDA6685D03EDF8A1D43DB5`

## 短测结果

| 项目 | 加速度计 | 陀螺仪 |
|---|---:|---:|
| 样本数 | 7,192 | 2,877 |
| 有效时长 | 62.510710497 s | 62.502017528 s |
| 实测频率 | 115.0363 Hz | 46.0145 Hz |
| 时间戳严格单调 | 是 | 是 |
| 重复时间戳 | 0 | 0 |
| 时间戳回退 | 0 | 0 |
| 相邻间隔中位数 | 8.693 ms | 21.732 ms |
| 相邻间隔最大值 | 8.695 ms | 21.734 ms |
| 超过 3 倍中位数的长间断 | 0 | 0 |
| 合矢量均值 | 9.912 m/s² | 0.165 rad/s |
| 合矢量标准差 | 0.809 m/s² | 0.694 rad/s |

## 结论

1. 加速度计与陀螺仪在同一采集会话中同步注册并写入独立 CSV。
2. 两个 CSV 均保留原始 `SensorEvent.timestamp`，没有进行滤波、插值、坐标旋转、单位换算或降采样。
3. 时间戳严格单调，无重复、回退或长时间间断。
4. 竖直放置静止时，加速度计合矢量约为 `9.8 m/s²`，量级和单位符合预期。
5. 陀螺仪静止值接近 `0 rad/s`；短测中的较大瞬时值来自操作过程中的设备转动，不是文件解析异常。
6. 页面进入后台后自动停止采集，CSV 与 `metadata.json` 均成功关闭并导出。

短测通过，可以进入操场 10 分钟正式试采。

## 证据文件

- `docs/evidence/task3-short-test/accelerometer.csv`
- `docs/evidence/task3-short-test/gyroscope.csv`
- `docs/evidence/task3-short-test/metadata.json`
- `docs/evidence/task3-short-test/task3-short-test-running.png`
- `docs/evidence/task3-short-test/task3-short-test-complete.png`