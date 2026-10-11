# 任务3实验①输入数据

- 会话：`20261008_195431_052`
- 采集方式：手持、匀速步行
- 原始数据：`raw/accelerometer.csv`、`raw/gyroscope.csv`、`raw/metadata.json`
- 采集说明：`collection_notes.json`
- 质量检查：`analysis/quality_report.json`
- 归档包：`task3-raw-data.zip`
- 校验文件：`SHA256SUMS.txt`

质量检查结论：表头、样本量、时间戳单调性、重复值、回退值、长时间间断、单位量级检查全部通过。

说明：原始元数据未单独记录明确朝向；本数据集根据重力方向补充了姿态观察，并标记为数据推断。