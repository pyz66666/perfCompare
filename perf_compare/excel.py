"""对比表格输出。

工作簿布局：
- 「说明」          —— 首个 sheet：两侧版本、阈值、判定口径、颜色图例、工作表说明
- 「汇总」          —— **套级唯一值**的对比，按类别分组，套名超链接到该套明细
- 「子项劣化汇总」   —— 跨套列出被判定劣化的子项，**按严重度倒序**
- 每个测试套一个 sheet —— 该套全部子项的明细（spark 系列为宽表）

**美化只改显示，不改数值**：数字格式与条件格式只影响呈现，单元格里仍是精确原值。
"""
import os

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .spark_items import SPARK_ITEMS

NOTES_SHEET = "说明"
SUMMARY_SHEET = "汇总"
DEGRADED_SHEET = "子项劣化汇总"

# 表头里的两侧名称默认值；可通过配置里的 `name` 指定（如系统名）——需求方 2026-10-12。
DEFAULT_LABELS = ("结果A", "结果B")

# 宽表明细的套：一行一个测试项，各次测量**横向并列**（需求方 2026-10-12）。
# 取值 = 该套每次测量的子项名；行序按源文件顺序（spark_items.py）；
# 文件自带的汇总值不作为普通行，而是放在明细末行归档（见 _写归档汇总行）。
_WIDE_LAYOUTS = {
    "spark": ("轮1", "轮2", "轮3"),
    "spark_docker": ("docker0", "docker1", "docker2"),
}

# 汇总表的类别分组（需求方 2026-10-16）：按此顺序输出，未列出的套归入「其它」。
_CATEGORIES = (
    (
        "基础性能测试",
        (
            "stream", "fio", "iozone3", "lmbench3", "netperf", "unixbench",
            "speccpu2017_int_single", "speccpu2017_int_max",
            "speccpu2017_fp_single", "speccpu2017_fp_max",
        ),
    ),
    (
        "场景化测试",
        (
            "nginx", "flink_nexmark", "flink_wordcount", "flink_6000c",
            "mysql_sysbench", "mysql_tpcc", "redis_docker", "spark", "spark_docker",
        ),
    ),
)
_OTHER_CATEGORY = "其它"

_套级口径说明 = (
    "套级值口径按测试套声明（见规划文档「对比项定义」）：多数为组内子项的几何平均，"
    "unixbench 取工具自带的 Index_Score，spark 系列为执行时间的平均值。"
)

# 样式。深色底白字表头 + 劣化/改善底色，均为“只改显示”。
_表头字体 = Font(bold=True, color="FFFFFF")
_表头填充 = PatternFill("solid", fgColor="1F4E79")
_类别字体 = Font(bold=True, color="1F4E79")
_类别填充 = PatternFill("solid", fgColor="DDEBF7")
_劣化填充 = PatternFill("solid", fgColor="FFC7CE")
_劣化字体 = Font(bold=True, color="9C0006")
_改善填充 = PatternFill("solid", fgColor="C6EFCE")
_链接字体 = Font(color="0563C1", underline="single")
# 差距百分比：带正负号与 % 单位；数值本身不动。
_百分比格式 = '+0.00"%";-0.00"%";0.00"%"'

# 劣化幅度分档（**纯静态填充**，不用条件格式 —— 数据条在 WPS 与 Excel 上表现可能不一致）。
# 顺序为从严重到轻微，取第一个命中的档。
_劣化分档 = (
    (50.0, PatternFill("solid", fgColor="C00000"), Font(bold=True, color="FFFFFF")),
    (20.0, PatternFill("solid", fgColor="FF7C80"), Font(bold=True, color="9C0006")),
)
# 改善幅度分档（同样只用静态填充）。
_改善分档 = ((20.0, PatternFill("solid", fgColor="A9D08E")),)


def write_excel(comparison, path, labels=DEFAULT_LABELS, info=None):
    """把一次比对写成 xlsx。

    `labels` 是两侧结果目录的显示名；`info` 是给「说明」页用的上下文
    （`baseline_path` / `candidate_path` / `threshold_pct` / `excluded_suites`）。
    """
    rows = comparison.rows()
    labels = tuple(labels)
    info = dict(info or {})

    workbook = openpyxl.Workbook()

    notes = workbook.active
    notes.title = NOTES_SHEET
    _写说明页(notes, labels, info)

    _写汇总表(workbook.create_sheet(title=SUMMARY_SHEET), comparison, labels)

    _写劣化汇总(workbook.create_sheet(title=DEGRADED_SHEET), comparison, labels)

    for suite in _suites_in_order(rows):
        detail = workbook.create_sheet(title=suite)
        if suite in _WIDE_LAYOUTS:
            _写宽表明细(detail, suite, _WIDE_LAYOUTS[suite], rows, labels)
        else:
            _写明细表(detail, suite, rows, labels)
        _修饰表(detail, wide=suite in _WIDE_LAYOUTS)

    _修饰表(notes, wide=False)
    _修饰表(workbook[SUMMARY_SHEET], wide=False)
    _修饰表(workbook[DEGRADED_SHEET], wide=False)

    _确保父目录存在(path)
    workbook.save(path)


def _写说明页(sheet, labels, info):
    """首个 sheet：让人拿到表就知道这是什么比对、怎么判的、颜色什么意思。"""
    threshold = info.get("threshold_pct")
    lines = [
        ("性能测试结果对比", None),
        ("", None),
        ("【对比的两个版本】", None),
        ("{0}（基线）".format(labels[0]), info.get("baseline_path")),
        ("{0}（对比）".format(labels[1]), info.get("candidate_path")),
        ("", None),
        ("【判定口径】", None),
        ("劣化阈值", "{0}%（严格大于该值才算劣化，等于不算）".format(threshold)),
        ("指标方向", "带宽／IOPS／吞吐越大越好；时延／耗时越小越好（按套与测试项声明）"),
        ("套级比对", "只比对两侧都包含的测试套；只在一侧出现的套不参与对比"),
        ("结论层级", "汇总给总体印象，子项劣化汇总给具体问题（套级归并存在稀释效应）"),
        ("套级值口径", _套级口径说明),
        ("", None),
        ("【颜色图例】", None),
        ("浅红／中红／深红", "劣化，颜色越深幅度越大（≥20% 中红、≥50% 深红）"),
        ("浅绿底", "改善（往变好的方向变化）"),
        ("差距百分比列", "带正负号与 % 单位；底色深浅表示劣化幅度"),
        ("", None),
        ("【工作表】", None),
        ("{0}".format(SUMMARY_SHEET), "套级唯一值对比，按类别分组；套名可点击跳到该套明细"),
        ("{0}".format(DEGRADED_SHEET), "跨套列出被判定劣化的子项，按严重度从高到低"),
        ("每套一个明细表", "该套全部子项的明细；spark 系列为宽表（各轮／各 docker 并列 + 平均值）"),
    ]
    excluded = info.get("excluded_suites") or []
    if excluded:
        lines.append(("只在一侧出现、未参与对比", "、".join(excluded)))

    for title, value in lines:
        sheet.append([title, value])

    sheet["A1"].font = Font(bold=True, size=14)
    for row_index, (title, value) in enumerate(lines, start=1):
        if title.startswith("【"):
            sheet.cell(row=row_index, column=1).font = _类别字体


def _写汇总表(sheet, comparison, labels):
    """套级对比，按类别分组；套名超链接到该套明细表。"""
    sheet.append(["测试套", labels[0], labels[1], "差距百分比", "是否劣化"])

    suite_rows = comparison.suite_rows()
    for category, members in _类别(suite_rows):
        sheet.append([category, None, None, None, None])
        sheet.cell(row=sheet.max_row, column=1).font = _类别字体
        for cell in sheet[sheet.max_row]:
            cell.fill = _类别填充
        for suite_row in suite_rows:
            if _类别名(suite_row.suite) != category:
                continue
            sheet.append(
                [
                    suite_row.label,
                    _显示值(suite_row.baseline_expr, suite_row.baseline),
                    _显示值(suite_row.candidate_expr, suite_row.candidate),
                    _格式百分比(suite_row.pct),
                    "是" if suite_row.degraded else "否",
                ]
            )
            _上色(sheet, sheet.max_row, sheet.max_row, 4, suite_row)
            _加超链接(sheet.cell(row=sheet.max_row, column=1), suite_row.suite)


def _写劣化汇总(sheet, comparison, labels):
    """跨套的劣化子项，**按严重度倒序**（最严重在最上面）。"""
    sheet.append(["测试套", "测试子项", labels[0], labels[1], "差距百分比"])
    degraded = [row for row in comparison.rows() if row.degraded]
    degraded.sort(key=_严重度, reverse=True)
    for row in degraded:
        sheet.append(
            [
                row.suite,
                _标签(row),
                _测量值(row.baseline),
                _测量值(row.candidate),
                _格式百分比(row.pct),
            ]
        )
        _上色(sheet, sheet.max_row, sheet.max_row, 5, row)


def _写明细表(sheet, suite, rows, labels):
    sheet.append(["测试子项", labels[0], labels[1], "差距百分比", "是否劣化"])
    for row in rows:
        if row.suite != suite:
            continue
        sheet.append(
            [
                _标签(row),
                _测量值(row.baseline),
                _测量值(row.candidate),
                _格式百分比(row.pct),
                "是" if row.degraded else "否",
            ]
        )
        _上色(sheet, sheet.max_row, sheet.max_row, 4, row)


def _写宽表明细(sheet, suite, measurements, rows, labels):
    """宽表：`测试子项 | 结果A 各次测量 + 平均 | 结果B 同 | 差距百分比 | 是否劣化`。

    只列出源文件里真实存在的测试项；文件自带的汇总值放在末行归档（需求方 2026-10-16），
    行序按**源文件顺序**排列（字母序会把 native_q10 排到 native_q2 前面，不可用）。
    """
    sheet.append(
        ["测试子项"]
        + ["{0}-{1}".format(labels[0], name) for name in measurements]
        + ["{0}-avg".format(labels[0])]
        + ["{0}-{1}".format(labels[1], name) for name in measurements]
        + ["{0}-avg".format(labels[1])]
        + ["差距百分比", "是否劣化"]
    )
    # 列序：测试子项(1) | A 各轮(n) | A-avg(1) | B 各轮(n) | B-avg(1) | 差距百分比 | 是否劣化
    # 故「差距百分比」= 1 + n + 1 + n + 1 + 1 = 2n + 4。曾误写成 2n+3，导致 % 格式与分档
    # 色错加到 B-avg 列上（平均值被显示成百分数，看起来像“对比结果”）。
    pct_column = len(measurements) * 2 + 4

    by_key = {(row.item, row.sub_item): row for row in rows if row.suite == suite}
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
        if average is not None:
            _上色(sheet, sheet.max_row, sheet.max_row, pct_column, average)

    _写归档汇总行(sheet, by_key, measurements, pct_column)


def _写归档汇总行(sheet, by_key, measurements, pct_column):
    """把**文件自带的汇总值**也留在明细末行归档（需求方 2026-10-16）。

    - `spark`：文件末尾的汇总值（解析时已 ÷3），放在「平均」列 —— 它是三轮的合计平均值，
      各轮列对该行不适用，写 `—`。
    - `spark_docker`：三个 docker 各自的末尾汇总值，以及它们的平均。

    这一行只作归档展示；是否劣化以汇总表那行为准（两者取的是同一个值）。
    """
    if ("汇总", "avg") not in by_key and ("汇总", "值") not in by_key:
        return

    target = by_key.get(("汇总", "avg")) or by_key.get(("汇总", "值"))
    sheet.append(
        ["汇总（文件自带）"]
        + [_归档值(by_key, name, "baseline") for name in measurements]
        + [_归档平均(by_key, measurements, "baseline")]
        + [_归档值(by_key, name, "candidate") for name in measurements]
        + [_归档平均(by_key, measurements, "candidate")]
        + [
            _格式百分比(target.pct if target is not None else None),
            "是" if target is not None and target.degraded else "否",
        ]
    )
    if target is not None:
        _上色(sheet, sheet.max_row, sheet.max_row, pct_column, target)


def _归档值(by_key, name, side):
    """归档行里某次测量的值；该行没有这一列的测量时写 `—`（不是「缺失」）。"""
    row = by_key.get(("汇总", name))
    if row is None:
        return "—"
    return _测量值(getattr(row, side))


def _归档平均(by_key, measurements, side):
    """归档行的平均值：优先用显式的 avg / 值，否则取各次测量的平均（仅用于展示）。"""
    for key in ("avg", "值"):
        row = by_key.get(("汇总", key))
        if row is not None:
            return _测量值(getattr(row, side))
    numbers_ = [
        getattr(by_key[("汇总", name)], side)
        for name in measurements
        if ("汇总", name) in by_key
        and getattr(by_key[("汇总", name)], side) is not None
    ]
    if not numbers_:
        return "—"
    return sum(numbers_) / len(numbers_)


def _上色(sheet, row_index, pct_row, pct_column, row):
    """劣化行标红、改善行标绿；差距单元格按幅度加深底色（百分比列用带符号百分号格式）。"""
    pct_cell = sheet.cell(row=pct_row, column=pct_column)
    pct_cell.number_format = _百分比格式
    if row.degraded:
        for cell in sheet[row_index]:
            cell.fill = _劣化填充
        pct_cell.font = _劣化字体
        _按幅度分档(pct_cell, _严重度(row), _劣化分档)
    elif _是否改善(row):
        for cell in sheet[row_index]:
            cell.fill = _改善填充
        _按幅度分档(pct_cell, abs(row.pct), _改善分档)


def _按幅度分档(cell, magnitude, grades):
    """按幅度给单元格换更醒目的底色（静态填充，跨软件一致）。"""
    for limit, fill, *rest in grades:
        if magnitude >= limit:
            cell.fill = fill
            if rest:
                cell.font = rest[0]
            return


def _是否改善(row):
    """差距是往“变好”的方向（且非零）。"""
    if row.pct is None or row.pct == 0 or row.higher_is_better is None:
        return False
    return row.pct > 0 if row.higher_is_better else row.pct < 0


def _严重度(row):
    """劣化的严重程度：往变差方向的幅度（越大越严重）。"""
    if row.pct is None:
        return 0.0
    return -row.pct if row.higher_is_better else row.pct


def _修饰表(sheet, wide=False):
    """表头样式、冻结首行（宽表再冻结首列）、自动筛选、列宽。"""
    last_column = max(sheet.max_column, 1)
    for cell in sheet[1][:last_column]:
        cell.font = _表头字体
        cell.fill = _表头填充
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "B2" if wide else "A2"
    sheet.auto_filter.ref = "A1:{0}{1}".format(get_column_letter(last_column), sheet.max_row)
    for index in range(1, last_column + 1):
        sheet.column_dimensions[get_column_letter(index)].width = _列宽(sheet, index)


def _列宽(sheet, index):
    """按该列最长内容估算列宽（第一列留给较长的测试子项名）。"""
    longest = 0
    for row in sheet.iter_rows(min_col=index, max_col=index):
        value = row[0].value
        if value is None:
            continue
        longest = max(longest, len(str(value)))
    if index == 1:
        return min(max(longest + 2, 14), 48)
    return min(max(longest + 2, 10), 22)


def _加超链接(cell, suite):
    cell.hyperlink = "#'{0}'!A1".format(suite)
    cell.font = _链接字体


def _类别(suite_rows):
    """按声明顺序给出 (类别名, 该类别下的套名集合)，并把未列出的套归入「其它」。"""
    present = [row.suite for row in suite_rows]
    result = []
    for category, members in _CATEGORIES:
        if any(suite in members for suite in present):
            result.append((category, members))
    if any(_类别名(suite) == _OTHER_CATEGORY for suite in present):
        result.append((_OTHER_CATEGORY, ()))
    return result


def _类别名(suite):
    for category, members in _CATEGORIES:
        if suite in members:
            return category
    return _OTHER_CATEGORY


def _确保父目录存在(path):
    """输出目录不存在时自动创建 —— 让用户为此失败一次是没必要的坑。"""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)


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
