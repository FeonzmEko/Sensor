# 任务2：实时加速度波形验证记录

- 验证日期：2026-09-27
- 真机：Xiaomi `25019PNF3C`（`ro.product.device=xuanyuan`），Android 17 / API 37
- 加速度计：`lsm6dsv Accelerometer Non-wakeup`，厂商 `STMicro`
- 申请档位：`SensorManager.SENSOR_DELAY_GAME`
- 实测采样频率：`115.0 Hz`（应用内 3 秒滑动窗口）
- 显示窗口：8 秒
- 单位与坐标：Android 设备坐标系 X/Y/Z，单位 `m/s²`
- 静止抽查：`X=0.30, Y=0.76, Z=9.78, |a|=9.81 m/s²`

## 验证结果

1. 真机持续注册 `SensorEventListener`，页面中的累计样本持续增长。
2. X/Y/Z 三条曲线分别以红、绿、蓝显示，曲线区域清晰可见。
3. 两次截图间累计样本由 `693` 增长到 `2198`，按 3 秒实测频率 `115.0 Hz` 计算与经过时间一致。
4. `clean testDebugUnitTest assembleDebug` 干净构建通过。
5. APK SHA-256：`5956D7E92F29E57473DC903C131A205040CADE5F94EF530209DB2A97FFE2BCFB`。

## 截图证据

- `docs/evidence/task2-real-device.png`
- `docs/evidence/task2-real-device-followup.png`

## 待人工完成

- 将真机截图发送课程群，完成打卡。

## 二十行监听器模板复核

- 复核日期：2026-09-27 20:35
- 真机重新安装、冷启动并运行监听器成功。
- 真机截图间隔 4 秒，累计样本由 925 增长到 1445，实测频率保持 115.0 Hz。
- 模拟器注入动态加速度后，X/Y/Z 三条曲线出现明显起伏，验证实时波形绘制链路。
- 真机截图：`docs/evidence/20-line-listener-real-device.png`
- 真机连续采样截图：`docs/evidence/20-line-listener-real-device-followup.png`
- 动态波形截图：`docs/evidence/20-line-listener-dynamic-emulator.png`

## 独立 Hello World 真机验证

- 页面：`HelloWorldActivity`，可由主页面按钮“打开二十行 Hello World”进入。
- 核心流程：`SensorManager` -> 默认加速度计 -> `SensorEventListener` -> `SENSOR_DELAY_GAME` -> `onPause()` 注销。
- 真机冷启动成功，传感器为 `lsm6dsv Accelerometer Non-wakeup`。
- 两次截图之间累计回调由 `605` 增长到 `990`，X/Y/Z 数值发生变化。
- 初始化截图：`docs/evidence/sensor-hello-world-real-device.png`
- 连续回调截图：`docs/evidence/sensor-hello-world-real-device-followup.png`