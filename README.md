# perf-compare

把同一被测系统在不同构建或配置下的性能测试结果自动横向比对，判定劣化项，产出 Excel 对比表格与 HTML 测试报告。

## 目标

- 从配置文件读入多个结果目录，其中一个为基线，其余为对比；
- 解析 16 个测试套的异构结果文件（长表文本 / SPEC CSV / JSON / 日志正则 / 裸数字列）；
- 按阈值与指标方向判定劣化，输出逐子项明细与结论性报告。

## 如何跑

尚未实现。可执行计划见 `docs/plans/active/`。

## 如何验证

尚未实现。验收标准与验证命令见计划文档。

## 外部依赖

- Python 3.8 ~ 3.13（见 `docs/adr/0001-stdlib-only-plus-openpyxl.md`）
- 唯一第三方依赖：`openpyxl`（写 xlsx），需支持离线安装
- 可选：能访问 `gitee.com` 以查询内核 commitId；离线时使用本地缓存（见 `docs/adr/0002-kernel-commit-via-gitee-tags.md`）

## 目录

| 路径 | 用途 |
| --- | --- |
| `测试结果模版/` | 一个结果目录的样例，解析器的事实依据与 fixture |
| `性能工程-数据自动对比分析报告项目规划.md` | 需求与决策记录 |
| `CONTEXT.md` | 术语表（只放术语，不放实现） |
| `docs/adr/` | 架构决策记录 |
| `docs/plans/active/` | 进行中的目标计划 |
