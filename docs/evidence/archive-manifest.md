# 第 2 课时 · 特征工程 归档记录

- 归档时间：2026-10-13
- 归档包：`lesson2-submission.zip`
- 体积：**18.47 MB**（167 个条目；解压后 32.9 MB / 163 个文件）
- **SHA-256**：`67B82EF56E1B2A1F66C787E521D32C9B66CF5995784DBDFBFCBD47D341F6567A`
- 校验文件：`lesson2-submission.zip.sha256`
- 包内另含 `SHA256SUMS.txt`（包内 162 个文件的逐项 SHA-256）与 `README-归档说明.md`

## 两处备份

| # | 位置 | 路径 | 状态 |
|---|---|---|---|
| ① | 仓库（主） | `D:\code\Sensor\data\lesson2-submission.zip`（+ `.sha256`） | 已生成、已入库 |
| ② | 课程资料目录（副） | `D:\study\大三上\多元感知融合\lesson2-submission.zip`（+ `.sha256`） | 已复制，SHA-256 与主一致 |

复验命令：

```powershell
(Get-FileHash "D:\code\Sensor\data\lesson2-submission.zip" -Algorithm SHA256).Hash
(Get-FileHash "D:\study\大三上\多元感知融合\lesson2-submission.zip" -Algorithm SHA256).Hash
# 两者都应等于 67B82EF56E1B2A1F66C787E521D32C9B66CF5995784DBDFBFCBD47D341F6567A
```

## 包内结构

| 目录 | 内容 |
|---|---|
| `data/` | 三个会话的原始数据（`accelerometer.csv` / `gyroscope.csv` / `labels.csv` / `metadata.json`）+ 元数据 |
| `analysis_outputs/` | 三个会话的派生结果：质量报告、窗口表、时域/频域特征表、频谱数据、图表、自动报告；主会话另含 `advanced/` 与 `advanced_stairs/` |
| `docs/` | `experiment2-report.md`、`experiment2-advanced.md`、`related-work.md`、`tasks2.md` 与 `evidence/` 截图 |
| `analysis/` | 分析工程源码（`src/` + `tests/` + `pyproject.toml`） |
| `README-归档说明.md` / `SHA256SUMS.txt` | 说明与逐文件校验值 |

> 说明：进阶流水线的自动特征矩阵缓存（约 14 MB/份）**未打包**，属可再生产物；
> 未打包的还有 Android 应用源码（在 git 仓库 `app/` 下）与 `.apk` 构建产物。

## 数据规模

| 会话 | 用途 | 时长 | 加计点数 | 打点 |
|---|---|---:|---:|---:|
| `20261012_114607_166` | 主数据（步行/楼梯/电梯/静止/骑行） | 1271.4 s | 146 266 | 14 |
| `20261013_101754_033` | 静止类补充（进阶实验） | 181.4 s | 20 866 | 1 |
| `20261013_215849_016` | 真实乘车负样本（地铁两段行驶 611 s） | 1029.6 s | 118 458 | 5 |
