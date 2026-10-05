"""对比表格输出。

工作簿布局（需求方 2026-10-05 修正）：
- 「汇总」        —— **套级唯一值**的对比（不是劣化项计数）
- 「子项劣化汇总」  —— 跨套列出被判定劣化的子项
- 每个测试套一个 sheet —— 该套全部子项的明细

「汇总」里的套级唯一值需要一个「把套内多个子项归并成单个值」的算法，该算法尚未确定
（阻塞项 O1）。确认之前一律写出 `待确认(O1)` 占位，**不自行发明算法** —— 否则一个错误的
数字会被当成权威结论读走。
"""
import openpyxl

SUMMARY_SHEET = "汇总"
DEGRADED_SHEET = "子项劣化汇总"
SUMMARY_HEADER = ["测试套", "结果A", "结果B", "差距百分比", "是否劣化"]
DEGRADED_HEADER = ["测试套", "测试项", "子项", "结果A", "结果B", "差距百分比"]
DETAIL_HEADER = ["测试项", "子项", "结果A", "结果B", "差距百分比", "是否劣化"]

_套级值占位 = "待确认(O1)"


def write_excel(comparison, path):
    """把一次比对写成 xlsx。"""
    rows = comparison.rows()
    suites = _suites_in_order(rows)

    workbook = openpyxl.Workbook()

    summary = workbook.active
    summary.title = SUMMARY_SHEET
    summary.append(SUMMARY_HEADER)
    for suite in suites:
        summary.append([suite] + [_套级值占位] * 4)

    degraded_sheet = workbook.create_sheet(title=DEGRADED_SHEET)
    degraded_sheet.append(DEGRADED_HEADER)
    for row in rows:
        if not row.degraded:
            continue
        degraded_sheet.append(
            [
                row.suite,
                row.item,
                row.sub_item,
                row.baseline,
                row.candidate,
                _格式百分比(row.pct),
            ]
        )

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
