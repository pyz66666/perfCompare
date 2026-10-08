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
DEGRADED_HEADER = ["测试套", "测试子项", "结果A", "结果B", "差距百分比"]
DETAIL_HEADER = ["测试子项", "结果A", "结果B", "差距百分比", "是否劣化"]

_套级口径说明 = (
    "套级值口径：套内子项按方向归一化后的几何平均（先合并再比；0 值排除）。"
    "【注意：套级算法未确认（O1），属临时口径，勿据此下结论】"
)


def write_excel(comparison, path):
    """把一次比对写成 xlsx。"""
    rows = comparison.rows()
    suites = _suites_in_order(rows)

    workbook = openpyxl.Workbook()

    summary = workbook.active
    summary.title = SUMMARY_SHEET
    summary.append(SUMMARY_HEADER)
    for suite_row in comparison.suite_rows():
        summary.append(
            [
                suite_row.label,
                _数值(suite_row.baseline),
                _数值(suite_row.candidate),
                _格式百分比(suite_row.pct),
                "是" if suite_row.degraded else "否",
            ]
        )
    summary.cell(row=1, column=6, value=_套级口径说明)

    degraded_sheet = workbook.create_sheet(title=DEGRADED_SHEET)
    degraded_sheet.append(DEGRADED_HEADER)
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
        detail.append(DETAIL_HEADER)
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

    workbook.save(path)


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


def _数值(value):
    """套级值缺失（例如套内没有任何正数可用）时显式说明，不留空白。"""
    return "无法计算" if value is None else value


def _suites_in_order(rows):
    return list(dict.fromkeys(row.suite for row in rows))
