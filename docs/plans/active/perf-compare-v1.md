# 计划：perf-compare 首版（v1）

**状态**：`active`（等待需求方确认架构与任务拆分后进入 Solve）

## Goal

让 `perf-compare` 能从一份配置文件出发，读入一个基线结果目录与若干对比结果目录，解析各测试套的异构结果文件，按阈值与指标方向判定劣化，产出 Excel 对比表格与 HTML 测试报告，并在报告末尾生成给分析用 agent 的提示词。

## Scope

- 输入：配置文件（基线与对比的结果目录路径、阈值、指标方向覆盖、内核版本号）
- 解析：14 个测试套（16 个减去 spark/spark_docker）
- 判定：阈值 + 方向 → 劣化
- 输出：Excel（sheet1 汇总 + 每套一 sheet）、HTML 报告（只含结论）、LLM 提示词

## Non-goals（首版不做）

- `spark`、`spark_docker`（裸数字列缺测试项名单，见规划文档 F4/F5）
- 对比文件之间的两两互比
- 机型／OS／页大小维度校验
- 阈值分档
- 套级汇总的几何平均列（O1 阻塞中）
- 任何第三方依赖（`openpyxl` 除外）

## Confirmed decisions

见 `性能工程-数据自动对比分析报告项目规划.md` 的「决策记录」（D1–D15）与 `docs/adr/0001`–`0003`。本计划不重复罗列，只引用。

## 架构

模块（deep module：小接口、大实现），依赖方向单向：`cli` → `config` / `resultdir` / `compare` → `excel` / `report`。

| 模块 | 接口 | 隐藏的实现 |
| --- | --- | --- |
| `config` | `load_config(path) -> Config` | 文件格式、默认值、校验（必须恰有一个基线、路径存在、阈值合法） |
| `resultdir` | `load(dir) -> ResultSet` | 文件发现与噪声过滤（`.idea/`、`.DS_Store`、前导空格文件名）、套↔文件映射、按格式族分派到解析器 |
| `compare` | `compare(baseline, candidate, config) -> Comparison` | 按 (套, 测试项, 子项) 配对、单边缺失处理、方向归一化、百分比计算、阈值判定、套级计数 |
| `excel` | `write_excel(comparison, path)` | openpyxl 细节、sheet 布局、汇总 sheet |
| `report` | `write_report(comparison, systems, path)` | HTML 结构、只输出结论、LLM 提示词生成 |
| `kernel` | `resolve(version) -> commitId \| None` | 版本号归一化、gitee 查询、本地缓存、离线降级 |
| `cli` | `main(argv) -> exit code` | 装配与错误呈现 |

**seam 决定**

- **格式族分派是真 seam**（5 个格式族 → ≥2 个 adapter）：放在 `resultdir` 内部，不对外暴露。外部只看到 `load(dir)`。
- **套级汇总不建 seam**：两个候选算法目前只有一个会被实现，预留接口属于投机抽象。改为把归并逻辑收敛到 `compare` 内的**单个函数**（locality），O1 确认后只改这一处。
- `report` 不自己查 commitId：内核版本到 commitId 的解析在装配层完成，`report` 只接收数据 —— 保持它是纯格式化模块，可离线测试。

**第一条端到端 tracer 路径**

CLI + 最小配置 + 一个只含 `fio.txt` 的基线与对比目录 → 解析 → 比对 → 写出单 sheet Excel + HTML 报告。先打通全链路，再横向铺开解析器覆盖面。

## Tasks

每个任务都是可独立验证的纵向切片。

- [ ] **T1 端到端最小闭环**：配置加载 + CLI 装配 + fio（长表族）解析 + 比对 + Excel + HTML 报告
- [ ] **T2 长表族补齐**：stream、iozone3、lmbench3、netperf、unixbench（含前导空格文件名）
- [ ] **T3 SPEC CPU2017**：4 个测试项（单核整数／单核浮点／多核整数／多核浮点），识别无效结果并告警
- [ ] **T4 场景化 JSON 族**：nginx、flink_nexmark、flink_wordcount（含 `performance_data` 字符串／数字归一化）
- [ ] **T5 场景化其余**：mysql_sysbench、mysql_tpcc（日志正则）、redis_docker、flink_6000c（破碎片段）
- [ ] **T6 阈值与方向**：配置文件加载、内置方向默认表、覆盖机制
- [ ] **T7 sheet1 汇总**：套内劣化项数／总项数 + 最差子项（几何平均列待 O1）
- [ ] **T8 内核 commitId**：归一化 + gitee 查询 + 本地缓存 + 离线降级
- [ ] **T9 报告完善**：劣化明细 + 两侧系统标识（内核版本／commitId／机型等）+ LLM 提示词
- [ ] **T10 端到端验收**：按下方验收场景跑通并留证据

## Verification

**命令**

```bash
python3 -m pytest -q                      # 单元与集成测试
python3 -m perf_compare --config <配置>    # 端到端运行（最终入口）
```

**验收场景**

| # | 场景 | 期望 |
| --- | --- | --- |
| A1 | 同一结果目录同时作为基线与对比 | 全部子项差异为 0、**零劣化项**；Excel 与报告均正常产出（最强不变量测试） |
| A2 | 人工把 `fio.txt` 的 `read_iops`@`blocksize-4k` 下调 20%，阈值设 5% | 该子项被判定劣化并出现在报告与汇总里；其余子项不受影响 |
| A3 | 对比目录缺少某个套的结果文件 | 标注「单边缺失」，不崩溃，其余套正常比对 |
| A4 | 阈值边界：变化百分比恰好等于阈值 | 按 D15 判**不劣化**（严格大于才算） |
| A5 | 断网（无代理）时运行 | 用本地缓存出 commitId；无缓存则报告标注「commitId 未知」，不失败 |
| A6 | 全量 `测试结果模版/` 作为对比、自比对 | 14 个套全部解析成功，无解析异常 |
| A7 | CPU2017 无效结果（F6） | 识别并告警，不产出误导性的劣化结论 |

## Progress

- Clarify 完成：决策 D1–D15、事实 F1–F7、非目标、阻塞项 O1–O5 均已记录。
- 仓库骨架、`CONTEXT.md`、3 条 ADR 已落地。
- 尚未写任何实现代码。

## Discoveries

- 结果文件格式比预期更碎：14 个套分布在 5 个格式族里，其中 `flink_6000c.txt` 是残缺片段（3 行 `"read-records": N,` + 一个裸数字），`mysql_tpcc.txt` 只有 1 行日志 —— 解析器必须对「格式退化」有明确行为。
- `spark_docker.out*` 末行无换行符，`wc -l` 会少计一行；解析不能依赖行数。
- 文件名 ` unixbench-master.txt` 带前导空格。
- 样例数据的 `performance_data` 类型不一致（F7），解析层必须先归一化再比对，否则会退化成字符串比较。

## Unresolved

- O1 套级汇总算法（阻塞 sheet1 汇总列）
- O2 Excel 手工案例（当前按 D5/D6 实现）
- O3 报告 HTML 样式与章节
- O4 阈值默认值与内核版本配置字段名
- O5 劣化判定是否含等号
