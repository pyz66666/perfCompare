"""对比表格输出。

工作簿布局（需求方 2026-10-05 修正）：
- 「汇总」        —— **套级唯一值**的对比（不是劣化项计数）
- 「子项劣化汇总」  —— 跨套列出被判定劣化的子项
- 每个测试套一个 sheet —— 该套全部子项的明细

「汇总」里的套级唯一值需要一个「把套内多个子项归并成单个值」的算法，该算法尚未确定
（阻塞项 O1）。确认之前一律写出 `待确认(O1)` 占位，**不自行发明算法** —— 否则一个错误的
数字会被当成权威结论读走。
"""
import os

import openpyxl

from .spark_items import SPARK_ITEMS

SUMMARY_SHEET = "汇总"
DEGRADED_SHEET = "子项劣化汇总"

# 表头里的两侧名称默认值；可通过配置里的 `name` 指定（如系统名）——需求方 2026-10-12。
DEFAULT_LABELS = ("结果A", "结果B")

# 宽表明细的套：一行一个测试项，各次测量**横向并列**（需求方 2026-10-12）。
# 取值 = 该套每次测量的子项名；行序按源文件顺序（spark_items.py），且不含「汇总」项。
_WIDE_LAYOUTS = {
    "spark": ("轮1", "轮2", "轮3"),
    "spark_docker": ("docker0", "docker1", "docker2"),
}

_套级口径说明 = (
    "套级值口径按测试套声明（见规划文档「对比项定义」）：多数为组内子项的几何平均，"
    "unixbench 取工具自带的 Index_Score，spark 系列为执行时间的平均值。"
)


def write_excel(comparison, path, labels=DEFAULT_LABELS):
    """把一次比对写成 xlsx。`labels` 是两侧结果目录的显示名（表头用）。"""
    rows = comparison.rows()
    suites = _suites_in_order(rows)
    labels = tuple(labels)

    workbook = openpyxl.Workbook()

    summary = workbook.active
    summary.title = SUMMARY_SHEET
    summary.append(["测试套", labels[0], labels[1], "差距百分比", "是否劣化"])
    for suite_row in comparison.suite_rows():
        summary.append(
            [
                suite_row.label,
                _显示值(suite_row.baseline_expr, suite_row.baseline),
                _显示值(suite_row.candidate_expr, suite_row.candidate),
                _格式百分比(suite_row.pct),
                "是" if suite_row.degraded else "否",
            ]
        )
    summary.cell(row=1, column=6, value=_套级口径说明)

    degraded_sheet = workbook.create_sheet(title=DEGRADED_SHEET)
    degraded_sheet.append(
        ["测试套", "测试子项", labels[0], labels[1], "差距百分比"]
    )
    for row in rows:
        if not row.degraded:
            continue
        degraded_sheet.append(
            [
                row.suite,
                _标签(row),
                row.baseline,
                row.candidate,
                _格式百分比(row.pct),
            ]
        )

    for suite in suites:
        detail = workbook.create_sheet(title=suite)
        if suite in _WIDE_LAYOUTS:
            _write_wide_sheet(detail, suite, _WIDE_LAYOUTS[suite], rows, labels)
            continue
        detail.append(["测试子项", labels[0], labels[1], "差距百分比", "是否劣化"])
        for row in rows:
            if row.suite != suite:
                continue
            detail.append(
                [
                    _标签(row),
                    _测量值(row.baseline),
                    _测量值(row.candidate),
                    _格式百分比(row.pct),
                    "是" if row.degraded else "否",
                ]
            )

    _确保父目录存在(path)
    workbook.save(path)


def _确保父目录存在(path):
    """输出目录不存在时自动创建 —— 让用户为此失败一次是没必要的坑。"""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)


def _write_wide_sheet(sheet, suite, measurements, rows, labels):
    """写宽表明细：`测试子项 | 结果A 各次测量 + 平均 | 结果B 同 | 差距百分比 | 是否劣化`。

    只列出源文件里真实存在的测试项（**不含「汇总」** —— 它属于汇总行），
    并按**源文件顺序**排列（字母序会把 native_q10 排到 native_q2 前面，不可用）。
    """
    sheet.append(
        ["测试子项"]
        + ["{0}-{1}".format(labels[0], name) for name in measurements]
        + ["{0}-avg".format(labels[0])]
        + ["{0}-{1}".format(labels[1], name) for name in measurements]
        + ["{0}-avg".format(labels[1])]
        + ["差距百分比", "是否劣化"]
    )

    by_key = {
        (row.item, row.sub_item): row for row in rows if row.suite == suite
    }
    present = {item for item, _ in by_key}

    for item in SPARK_ITEMS:
        if item not in present:
            continue
        average = by_key.get((item, "avg"))
        sheet.append(
            [item]
            + [_宽表值(by_key, item, name, "baseline") for name in measurements]
            + [_平均值字段(average, "baseline")]
            + [_宽表值(by_key, item, name, "candidate") for name in measurements]
            + [_平均值字段(average, "candidate")]
            + [
                _格式百分比(average.pct if average is not None else None),
                "是" if average is not None and average.degraded else "否",
            ]
        )


def _宽表值(by_key, item, sub_item, side):
    row = by_key.get((item, sub_item))
    if row is None:
        return "缺失"
    return _测量值(getattr(row, side))


def _平均值字段(average, side):
    if average is None:
        return "缺失"
    return _测量值(getattr(average, side))


def _格式百分比(pct):
    """百分比按 2 位小数写出。

    浮点误差会产出 -7.999999999999999 这种数字，放进交付物里很难看。
    基线为 0 时百分比无定义，显式写「无法比较」，避免留空白被误读成漏数据。
    """
    return "无法比较" if pct is None else round(pct, 2)


def _标签(row):
    """测试项与子项合并成一列，用 `-` 连接（需求方 2026-10-05）。

    例：`randread_bw_blocksize` + `blocksize-1024k` → `randread_bw_blocksize-blocksize-1024k`。
    """
    if not row.sub_item:
        return row.item
    return "{0}-{1}".format(row.item, row.sub_item)


def _测量值(value):
    """单边缺失（某侧没有这个测量项，例如两侧核数不同）时显式写「缺失」，不留空白。"""
    return "缺失" if value is None else value


def _显示值(expr, value):
    """有显示表达式时写 **Excel 公式**（保留原值可追溯，决策 D19），否则写数值。"""
    if expr is not None:
        return expr
    return _数值(value)


def _数值(value):
    """套级值缺失（例如套内没有任何正数可用）时显式说明，不留空白。"""
    return "无法计算" if value is None else value


def _suites_in_order(rows):
    return list(dict.fromkeys(row.suite for row in rows))
