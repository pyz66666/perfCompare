"""比对：把基线与一个对比结果目录逐 (套, 测试项, 子项) 比较，判定劣化。

差异百分比一律相对基线计算：(对比值 - 基线值) / 基线值 × 100。

除了逐子项的比对面，还给出**套级唯一值**：把套内多个子项归并成单个代表值后再比较，
用于「汇总」视图。归并口径见 `_suite_level`。
"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Row:
    """一个子项的比对面。"""

    suite: str
    item: str
    sub_item: str
    baseline: Optional[float]
    candidate: Optional[float]
    pct: Optional[float]
    degraded: bool


@dataclass(frozen=True)
class SuiteRow:
    """一个汇总行：测试套 + 分组（如单核／多核）。"""

    suite: str
    label: str
    baseline: Optional[float]
    candidate: Optional[float]
    pct: Optional[float]
    degraded: bool


class Comparison:
    """一次比对的全部结果：逐子项 + 套级。"""

    def __init__(self, rows, suite_rows):
        self._rows = list(rows)
        self._suite_rows = list(suite_rows)

    def rows(self):
        """按稳定顺序返回全部逐子项比对面。"""
        return list(self._rows)

    def suite_rows(self):
        """按稳定顺序返回全部套级比对面。"""
        return list(self._suite_rows)


def compare(baseline, candidate, threshold_pct):
    """比对基线与对比结果集，返回 Comparison。

    配对按两侧测量值的**并集**进行：测试项名编码了核数（如 `384_Core`），两侧核数不同时
    项名对不上，此时各自独有的项列为「单边缺失」（值为 None），既不崩溃也不被静默忽略。
    """
    base_map = {
        (suite, item, sub_item): value
        for suite, item, sub_item, value in baseline.observations()
    }
    cand_map = {
        (suite, item, sub_item): value
        for suite, item, sub_item, value in candidate.observations()
    }

    rows = []
    for key in sorted(set(base_map) | set(cand_map)):
        suite, item, sub_item = key
        base_value = base_map.get(key)
        cand_value = cand_map.get(key)
        if base_value is None or cand_value is None or base_value == 0:
            # 单边缺失，或基线为 0（真实数据里 lmbench3 的 RPC/UDP、RPC/TCP 就是 0.0）：
            # 百分比无定义。
            pct = None
        else:
            pct = (cand_value - base_value) / base_value * 100.0
        rows.append(
            Row(
                suite=suite,
                item=item,
                sub_item=sub_item,
                baseline=base_value,
                candidate=cand_value,
                pct=pct,
                degraded=_is_degraded(pct, threshold_pct, _higher_is_better(item)),
            )
        )
    return Comparison(rows, _suite_level(rows, threshold_pct))


def _is_degraded(pct, threshold_pct, higher_is_better=True):
    """劣化 = 朝**变差**的方向变化，且幅度严格大于阈值（决策记录 D15）。

    - 越大越好的指标（带宽、IOPS、吞吐）：**变小**才是劣化。
    - 越小越好的指标（时延、耗时）：**变大**才是劣化。

    方向若一律按「越大越好」处理，时延上升会被判成没劣化 —— 会漏报，比崩溃更危险。
    百分比无定义（基线为 0、单边缺失）时无从判定，一律不算劣化。
    """
    if pct is None:
        return False
    if higher_is_better:
        return -pct > threshold_pct
    return pct > threshold_pct


# 「越小越好」的测试项。这是一个**临时口径**：完整的方向表与配置覆盖属于 T6，
# 尚未实现，因此这里只列出当前已接入的测试套里已知的延迟类测试项。
_LOWER_IS_BETTER_ITEMS = ("Processor_Processes", "Context_switching_ctxsw")


# 按测试套声明的**汇总口径**（需求方逐套确认，各套不同）：
#   group_by —— 先按什么分组求唯一值：`core` = 单核／多核（核数不固定，故按项名是否含
#               "1core" 识别），`item` = 每个测试项各自一组。
#   combine  —— 是否把各分组的值再合并成**一个**汇总值（对分组值再求几何平均）。
#   pick     —— 若给出，则分组的唯一值直接取这个子项（测试工具自带的综合分），不再另算平均。
# 未声明的测试套沿用临时口径：整套子项归一化后取几何平均（**算法未确认，见 O1**）。
_SUMMARY_RECIPES = {
    "stream": {"group_by": "core", "combine": True},
    "fio": {"group_by": "item", "combine": True},
    "iozone3": {"group_by": "item", "combine": True},
    "netperf": {"group_by": "item", "combine": True},
    # lmbench3 分成两行，且**时延用原始值**（不取倒数）：方向只影响劣化判定。
    "lmbench3": {
        "partition": [
            ("lmbench（带宽）", ["Local_bandwidths"], True),
            ("lmbench（时延）", None, False),
        ]
    },
    "unixbench": {"group_by": "core", "pick": "System_Benchmarks_Index_Score"},
    # 行名按需求方要求写作 mysql-tpcc（连字符，非下划线）。
    "mysql_tpcc": {"group_by": "item", "combine": True, "label": "mysql-tpcc"},
    # nginx：四个 workload 各一行，另加一行四项的几何平均。
    "nginx": {
        "partition": [
            ("nginx（http短连接）", ["http_short"], True),
            ("nginx（http长连接）", ["http_long"], True),
            ("nginx（https短连接）", ["https_short"], True),
            ("nginx（https长连接）", ["https_long"], True),
        ],
        "combine_all": "nginx（几何平均值）",
    },
}


def _squash(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _is_single_core(item):
    """单核项识别：`Index_Values_1core`、`1_Core` 都归一化成含 `1core`。"""
    return "1core" in _squash(item)


def _higher_is_better(item):
    if "latenc" in item.lower():
        return False
    return item not in _LOWER_IS_BETTER_ITEMS


def _normalized(value, higher_is_better):
    """（已不再使用）原先用于把测量值归一化成「越大越好」，现已改为用原始值计算。"""
    if value is None or value <= 0:
        return None
    return value if higher_is_better else 1.0 / value


def _geometric_mean(values):
    """在对数域求几何平均，**非正值（含 0 与缺失）一律排除**。

    排除 0 值：几何平均要求全部为正数，只要有一个 0 整组结果就会变成 0（需求方确认）。
    用对数域：fio 有 96 个子项、量级约 1e5，朴素连乘乘积约 1e480 会溢出成 inf，
    而 Excel 存不下 inf（读回来是空值）。
    """
    usable = [value for value in values if value is not None and value > 0]
    if not usable:
        return None
    return math.exp(sum(math.log(value) for value in usable) / len(usable))


def _suite_level(rows, threshold_pct):
    """按各测试套声明的**汇总口径**产出汇总行。

    口径由 `_SUMMARY_RECIPES` 按套声明，因为各套不同（需求方逐套确认）。
    未声明的套沿用临时口径：整套子项按方向归一化后取几何平均（**算法未确认，见 O1**）。
    """
    suite_rows = []
    for suite in dict.fromkeys(row.suite for row in rows):
        suite_rows.extend(_suite_rows_for(suite, rows, threshold_pct))
    return suite_rows


def _suite_rows_for(suite, rows, threshold_pct):
    suite_all = [row for row in rows if row.suite == suite]
    recipe = _SUMMARY_RECIPES.get(suite)
    if recipe is None:
        return [_make_suite_row(suite, suite, suite_all, None, threshold_pct)]

    if recipe.get("partition") is not None:
        return _partition_rows(suite, recipe, suite_all, threshold_pct)

    groups = _groups_of(recipe, suite_all)

    pick = recipe.get("pick")
    if recipe.get("combine"):
        group_rows = list(groups.values())
        return [
            _row_from_values(
                suite,
                recipe.get("label", suite),
                _geometric_mean([_group_value(g, pick, "baseline") for g in group_rows]),
                _geometric_mean([_group_value(g, pick, "candidate") for g in group_rows]),
                threshold_pct,
            )
        ]

    return [
        _make_suite_row(
            suite, "{0}（{1}）".format(suite, name), rows_in_group, pick, threshold_pct
        )
        for name, rows_in_group in groups.items()
    ]


def _partition_rows(suite, recipe, suite_all, threshold_pct):
    """按显式划分产出多行（`partition` 每项 = 行名、测试项集合、方向）。

    集合为 `None` 表示「其余全部测试项」。另外 `combine_all` 可指定**再补一行**
    「全部测试项合并值」—— nginx 的「几何平均值」行即此类。
    """
    partition = recipe["partition"]
    listed = set()
    for _, items, _ in partition:
        if items is not None:
            listed.update(items)

    rows = []
    for label, items, higher_is_better in partition:
        if items is None:
            selected = [row for row in suite_all if row.item not in listed]
        else:
            selected = [row for row in suite_all if row.item in items]
        rows.append(_combined_row(suite, label, selected, threshold_pct, higher_is_better))

    combine_all = recipe.get("combine_all")
    if combine_all is not None:
        rows.append(_combined_row(suite, combine_all, suite_all, threshold_pct, True))
    return rows


def _combined_row(suite, label, selected, threshold_pct, higher_is_better):
    return _row_from_values(
        suite,
        label,
        _combined_value(selected, "baseline"),
        _combined_value(selected, "candidate"),
        threshold_pct,
        higher_is_better,
    )


def _combined_value(rows, side):
    """若干测试项合并成一个值：每个测试项内部先求几何平均，再对各测试项的值求几何平均。"""
    groups = {}
    for row in rows:
        groups.setdefault(row.item, []).append(row)
    return _geometric_mean(
        [_geometric_mean([getattr(row, side) for row in group]) for group in groups.values()]
    )


def _groups_of(recipe, suite_all):
    """按口径分组。`core` → 单核／多核；`item` → 每个测试项一组。"""
    by_item = recipe.get("group_by") == "item"
    groups = {}
    for row in suite_all:
        if by_item:
            key = row.item
        else:
            key = "单核" if _is_single_core(row.item) else "多核"
        groups.setdefault(key, []).append(row)
    return groups


def _group_value(group_rows, pick, side):
    """一个分组的唯一值：取指定子项，或对该分组的子项**用原始值**求几何平均。

    用原始值（不按方向取倒数）是需求方确认的口径；方向只用于判定劣化。
    """
    if pick is not None:
        return _pick_sub_item(group_rows, pick, side)
    return _geometric_mean([getattr(row, side) for row in group_rows])


def _make_suite_row(suite, label, group_rows, pick, threshold_pct):
    return _row_from_values(
        suite,
        label,
        _group_value(group_rows, pick, "baseline"),
        _group_value(group_rows, pick, "candidate"),
        threshold_pct,
    )


def _row_from_values(suite, label, base_value, cand_value, threshold_pct, higher_is_better=True):
    pct = None
    if base_value is not None and cand_value is not None and base_value != 0:
        pct = (cand_value - base_value) / base_value * 100.0
    return SuiteRow(
        suite=suite,
        label=label,
        baseline=base_value,
        candidate=cand_value,
        pct=pct,
        degraded=_is_degraded(pct, threshold_pct, higher_is_better),
    )


def _pick_sub_item(group_rows, sub_item, side):
    """取分组里指定子项的值；没有该子项则为 None（单边缺失或口径不适用）。"""
    for row in group_rows:
        if row.sub_item == sub_item:
            return getattr(row, side)
    return None
