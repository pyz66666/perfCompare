"""对比表格输出：首表为汇总，其余每个测试套一个子项明细表。

表头按决策记录 D5/D6：明细表的 `测试子项` 按 CONTEXT.md 拆成 `测试项` 与 `子项` 两列
（两者在本上下文里是不同概念），待需求方提供 Excel 案例后核对（阻塞项 O2）。
"""
import openpyxl

SUMMARY_SHEET = "汇总"
SUMMARY_HEADER = ["测试套", "劣化项数", "总项数"]
DETAIL_HEADER = ["测试项", "子项", "结果A", "结果B", "差距百分比", "是否劣化"]


def write_excel(comparison, path):
    """把一次比对写成 xlsx。"""
    rows = comparison.rows()
    suites = _suites_in_order(rows)

    workbook = openpyxl.Workbook()
    summary = workbook.active
    summary.title = SUMMARY_SHEET
    summary.append(SUMMARY_HEADER)
    for suite in suites:
        suite_rows = [row for row in rows if row.suite == suite]
        degraded = [row for row in suite_rows if row.degraded]
        summary.append([suite, len(degraded), len(suite_rows)])

    for suite in suites:
        detail = workbook.create_sheet(title=suite)
        detail.append(DETAIL_HEADER)
        for row in rows:
            if row.suite != suite:
                continue
            detail.append(
                [
                    row.item,
                    row.sub_item,
                    row.baseline,
                    row.candidate,
                    _格式百分比(row.pct),
                    "是" if row.degraded else "否",
                ]
            )

    workbook.save(path)


def _格式百分比(pct):
    """百分比无定义（基线为 0）时显式写出「无法比较」，避免留空白被误读成漏数据。"""
    return "无法比较" if pct is None else pct


def _suites_in_order(rows):
    return list(dict.fromkeys(row.suite for row in rows))
