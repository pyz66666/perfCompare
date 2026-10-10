# perf-compare

把同一被测系统在不同构建或配置下的性能测试结果自动横向比对，判定劣化项，产出 Excel 对比表格与 HTML 测试报告。

> 📖 **面向使用者的操作手册见 [使用指南.md](./使用指南.md)** —— 配置怎么写、命令怎么跑、结果输出在哪、报错去哪看（含常见坑排查）。本 README 面向开发与维护。

## 如何跑

需要 Python 3.8 ~ 3.13。唯一第三方依赖是 `openpyxl`（写 xlsx）。

```bash
# 1. 准备配置文件（仓库自带可直接运行的示例，复制后改路径）
cp compare.example.json compare.json

# 2. 在项目目录下执行（输出目录需先存在）
mkdir -p out
python3 -m perf_compare --config compare.json --excel out/对比表格.xlsx
```

⚠️ `python3 -m perf_compare` **必须在项目目录下运行**，否则报 `No module named perf_compare`。另两种方式（设 `PYTHONPATH`、或 `pip install .` 后直接用 `perf-compare` 命令）见使用指南。

`compare.json` 是你的本地配置（可能含内网路径），已被 `.gitignore` 排除；仓库里只保留示例 `compare.example.json`。完整的配置字段说明、排查方法见 [使用指南.md](./使用指南.md)。

命令行参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--config` | 是 | 配置文件路径（JSON） |
| `--excel` | 是 | 对比表格输出路径（`.xlsx`） |
| `--log-dir` | 否 | 报错日志目录，默认 `logs/` |

### 配置文件格式

```json
{
  "baseline": {
    "path": "/home/AutoBench/report/950/openEuler-24.03/64K/baseline",
    "kernel_version": "6.6.0-72.3.0"
  },
  "candidates": [
    {
      "path": "/home/AutoBench/report/950/openEuler-24.03/64K/compare",
      "kernel_version": "6.6.0-72.5.0"
    }
  ],
  "threshold_pct": 5.0
}
```

- `baseline` / `candidates[].path`：**结果目录**的路径。结果文件**平铺**在该目录下（如 `<dir>/fio.txt`）；也兼容按类别放在 `基础性能测试/`、`场景化测试/` 子目录里的布局。目录里缺失的套会被跳过（不报错），运行时会打印读到与未找到的套清单。
- `kernel_version`：被测系统的内核版本-发布号，用于换算 commitId（可留空）。
- `threshold_pct`：劣化阈值，百分比。变化幅度**严格大于**该值才算劣化。
- **基线不写死在代码里** —— 换版本只需改配置里哪个路径放在 `baseline`。

> ⚠️ 首版只接受**恰好一个** `candidates` 条目；给多个会以退出码 2 明确报错（多对比的表格布局未定，见规划文档 O8）。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 执行出错，完整堆栈已写入日志（见下） |
| 2 | 参数合法但不支持（例如给了多个对比目录） |
| 3 | 两个结果目录里一个测试套都没读到（路径填错），未生成表格 |

每次运行都会在终端打印**两侧各读到哪些测试套、本工具认识但未找到哪些**，便于判断数据是否不全。

## 报错日志

出错时终端只提示一行日志路径，**完整堆栈追加写入**日志文件，便于事后排查：

```
logs/perf-compare.log
```

每条记录含时间、命令行参数与完整 traceback。日志目录由 `--log-dir` 指定，默认 `logs/`（已加入 `.gitignore`）。

## 输出

一份 xlsx，包含三类工作表：

| 工作表 | 内容 |
| --- | --- |
| `汇总` | **套级/分组级**的唯一值对比（每行 = 一个测试套或它的一个分组） |
| `子项劣化汇总` | 跨套列出**被判定劣化**的每个子项 |
| 每个测试套一个 sheet | 该套全部子项的明细 |

- 明细表的标签把**测试项与子项合并成一列**，用 `-` 连接：`read_iops_blocksize-blocksize-4k`。
- 差距百分比保留 2 位小数。
- 百分比无定义时显式写「无法比较」（基线为 0），某侧缺失时写「缺失」—— 不留空白，避免被误读成漏数据。
- 需要单位换算的汇总值**以 Excel 公式呈现、保留原数据**（如 `=116445015/1000`）。

> **劣化结论分两级报**：汇总给总体印象，子项劣化汇总给具体问题。因为套级/分组级归并存在**稀释效应** —— 单个子项大幅劣化可能在汇总层被摊薄到阈值以下（实测：某时延子项 +30%，其所属的时延分组只体现 +1.32%）。

## 支持的测试套（13 个）

| 类别 | 测试套 |
| --- | --- |
| 基础性能 | `stream`、`fio`、`iozone3`、`lmbench3`、`netperf`、`unixbench` |
| 场景化 | `nginx`、`flink_nexmark`、`flink_wordcount`、`flink_6000c`、`mysql_sysbench`、`mysql_tpcc`、`redis_docker` |

尚未接入：`speccpu2017`（按需求方指示搁置）、`spark`、`spark_docker`（结果文件是零标签裸数字列，缺测试项名单）。

各套的汇总口径**逐套不同**（有的取工具自带的综合分，有的算子项几何平均，有的分单核/多核多行），统一在 `perf_compare/compare.py` 的 `_SUMMARY_RECIPES` 中按套声明；口径定义见 `性能工程-数据自动对比分析报告项目规划.md` 的「对比项定义」。

## 如何验证

```bash
python3 -m pytest -q
```

修改任何解析器后，必须用 `测试结果模版/` 下的样例数据验证 —— 它覆盖了 5 种异构格式族与多个真实坑（前导空格文件名、末行无换行、0 值、浮点溢出等）。

## 目录

| 路径 | 用途 |
| --- | --- |
| `perf_compare/` | 实现：`config` / `resultdir` / `compare` / `excel` / `cli` |
| `tests/` | 测试（只穿过各模块约定的 seam） |
| `测试结果模版/` | 一个结果目录的样例，解析器的事实依据与 fixture |
| `性能工程-数据自动对比分析报告项目规划.md` | 需求、决策记录（D 编号）、事实（F 编号）、待办 |
| `CONTEXT.md` | 术语表（只放术语，不放实现） |
| `docs/adr/` | 架构决策记录 |
| `docs/plans/active/` | 进行中的目标计划 |

## 外部依赖

- Python 3.8 ~ 3.13（见 `docs/adr/0001-stdlib-only-plus-openpyxl.md`）
- `openpyxl`：唯一必需第三方依赖，需支持离线安装
- 可选：能访问 `gitee.com` 以查询内核 commitId；离线时使用本地缓存（见 `docs/adr/0002-kernel-commit-via-gitee-tags.md`）
