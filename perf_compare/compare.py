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
    # 该指标「越大越好」为 True。表格用它区分「劣化（红）」与「改善（绿）」。
    higher_is_better: Optional[bool] = True


@dataclass(frozen=True)
class SuiteRow:
    """一个汇总行：测试套 + 分组（如单核／多核）。"""

    suite: str
    label: str
    baseline: Optional[float]
    candidate: Optional[float]
    pct: Optional[float]
    degraded: bool
    # 需要单位换算的行，按需求方要求以 Excel 公式呈现、保留原值（决策 D19）。
    baseline_expr: Optional[str] = None
    candidate_expr: Optional[str] = None
    higher_is_better: Optional[bool] = True


class Comparison:
    """一次比对的全部结果：逐子项 + 套级。"""

    def __init__(self, rows, suite_rows, excluded_suites=None):
        self._rows = list(rows)
        self._suite_rows = list(suite_rows)
        self._excluded_suites = list(excluded_suites or [])

    def rows(self):
        """按稳定顺序返回全部逐子项比对面。"""
        return list(self._rows)

    def suite_rows(self):
        """按稳定顺序返回全部套级比对面。"""
        return list(self._suite_rows)

    def excluded_suites(self):
        """只在某一侧出现、因而未参与对比的测试套。"""
        return list(self._excluded_suites)


def compare(baseline, candidate, threshold_pct):
    """比对基线与对比结果集，返回 Comparison。

    **只比对两侧都包含的测试套**（需求方 2026-10-12）：基线有 5 个套、对比只有 2 个时，
    只比这 2 个；只在一侧出现的套不参与对比，也不产生满屏「缺失」行 —— 被排除的套可查
    `excluded_suites()`。

    同一套**内部**若测试项名对不上（例如两侧核数不同导致 `384_Core` 对 `256_Core`），
    仍按单边缺失显式列出，不静默丢弃。
    """
    base_map = {
        (suite, item, sub_item): value
        for suite, item, sub_item, value in baseline.observations()
    }
    cand_map = {
        (suite, item, sub_item): value
        for suite, item, sub_item, value in candidate.observations()
    }

    base_suites = {suite for suite, _, _ in base_map}
    cand_suites = {suite for suite, _, _ in cand_map}
    common_suites = base_suites & cand_suites
    excluded_suites = sorted((base_suites | cand_suites) - common_suites)

    rows = []
    for key in sorted(key for key in set(base_map) | set(cand_map) if key[0] in common_suites):
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
                degraded=(
                    _is_degraded(pct, threshold_pct, _higher_is_better(suite, item))
                    if _should_judge(suite, sub_item)
                    else False
                ),
                higher_is_better=_higher_is_better(suite, item),
            )
        )
    return Comparison(rows, _suite_level(rows, threshold_pct), excluded_suites)


def _is_degraded(pct, threshold_pct, higher_is_better=True):
    """劣化 = 朝**变差**的方向变化，且幅度严格大于阈值（决策记录 D15）。

    - 越大越好的指标（带宽、IOPS、吞吐）：**变小**才是劣化。
    - 越小越好的指标（时延、耗时）：**变大**才是劣化。

    方向若一律按「越大越好」处理，时延上升会被判成没劣化 —— 会漏报，比崩溃更危险。
    百分比无定义（基线为 0、单边缺失）时无从判定，一律不算劣化。

    **按显示精度（2 位小数）比较**：`3815.46 × 0.95` 的 pct 实际是 `-5.0000000000000036`，
    直接与阈值比较会判成劣化，而表格显示的是 `-5.00%` —— 结论与显示自相矛盾。四舍五入到
    2 位后再比较，判定与用户看到的一致。
    """
    if pct is None:
        return False
    magnitude = -pct if higher_is_better else pct
    return round(magnitude, 2) > round(threshold_pct, 2)


# 「越小越好」的测试项。这是一个**临时口径**：完整的方向表与配置覆盖属于 T6，
# 尚未实现，因此这里只列出当前已接入的测试套里已知的延迟类测试项。
_LOWER_IS_BETTER_ITEMS = ("Processor_Processes", "Context_switching_ctxsw")

# 整个套都「越小越好」的测试套 —— spark 系列的值是**执行时间**（需求方 2026-10-12）。
# 其项名（native_qN）不含任何方向线索，只能按套声明，不能靠名字猜。
_LOWER_IS_BETTER_SUITES = ("spark", "spark_docker")

# 只对指定子项判定劣化、其余子项仅展示（需求方口径：spark 只对比平均值）。
_ONLY_JUDGE_SUB_ITEMS = {"spark": ("avg",), "spark_docker": ("avg",)}


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
    # flink_nexmark：只取 testcase_name == "sum" 那一条作为结果。
    "flink_nexmark": {"partition": [("flink_nexmark", ["sum"], True)]},
    # redis_docker：set / get 各一行（各自四个 docker 的几何平均），再加一行两者合并。
    "redis_docker": {
        "partition": [
            ("redis_docker（set）", ["set"], True),
            ("redis_docker（get）", ["get"], True),
        ],
        "combine_all": "redis_docker（几何平均值）",
    },
    # mysql_sysbench：每个测试项一行（只取 TPS 的四次平均）。
    "mysql_sysbench": {
        "partition": [
            ("mysql_sysbench（oltp_point_select）", ["oltp_point_select"], True),
            ("mysql_sysbench（oltp_read_only）", ["oltp_read_only"], True),
            ("mysql_sysbench（oltp_read_write）", ["oltp_read_write"], True),
        ]
    },
    # flink_wordcount：值 ÷1000，且该除法在 Excel 里以公式呈现、保留原值（决策 D19）。
    "flink_wordcount": {"group_by": "item", "combine": True, "display_scale": 1000},
    # flink_6000c：三行 read-records 求和取平均（**算术平均**，不是几何平均）。
    "flink_6000c": {"group_by": "item", "combine": True, "aggregate": "mean"},
    # spark：汇总行取文件末尾的汇总值（解析时已 ÷3 得到单轮平均）；方向为「越小越好」。
    "spark": {"partition": [("spark", ["汇总"], False)]},
    # spark_docker：汇总行 = 三个 docker 汇总值的**平均**；方向为「越小越好」。
    "spark_docker": {
        "partition": [("spark_docker", ["汇总"], False)],
        "aggregate": "mean",
    },
    # speccpu2017 是四个独立套（需求方 2026-10-16），各出一行汇总；SPECrate 越大越好。
    "speccpu2017_int_single": {
        "partition": [("speccpu2017（单核整数）", ["SPECrate2017_int_base"], True)]
    },
    "speccpu2017_int_max": {
        "partition": [("speccpu2017（多核整数）", ["SPECrate2017_int_base"], True)]
    },
    "speccpu2017_fp_single": {
        "partition": [("speccpu2017（单核浮点）", ["SPECrate2017_fp_base"], True)]
    },
    "speccpu2017_fp_max": {
        "partition": [("speccpu2017（多核浮点）", ["SPECrate2017_fp_base"], True)]
    },
}


def _squash(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _is_single_core(item):
    """单核项识别：`Index_Values_1core`、`1_Core` 都归一化成含 `1core`。"""
    return "1core" in _squash(item)


def _higher_is_better(suite, item):
    """方向按「套 + 测试项」判断。

    spark 系列整个套的值都是执行时间（越小越好），项名里没有方向线索，只能按套声明；
    其余套仍按项名里的延迟类线索判断（T6 会补完整的方向表与配置覆盖）。
    """
    if suite in _LOWER_IS_BETTER_SUITES:
        return False
    if "latenc" in item.lower():
        return False
    return item not in _LOWER_IS_BETTER_ITEMS


def _should_judge(suite, sub_item):
    """该子项是否参与劣化判定；未声明「只判定若干子项」的套一律判定。"""
    judged = _ONLY_JUDGE_SUB_ITEMS.get(suite)
    if judged is None:
        return True
    return sub_item in judged


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
    if len(usable) == 1:
        # 单个值的几何平均就是它本身。走对数域会引入浮点误差
        # （116445015 → 116445014.99999988），会让 D19 的公式失去"保留原数据"的意义。
        return usable[0]
    return math.exp(sum(math.log(value) for value in usable) / len(usable))


def _arithmetic_mean(values):
    """算术平均（flink_6000c 的三值求和取平均用这个，不是几何平均）。"""
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _aggregate(values, name):
    """按口径选择归并方式：`mean` = 算术平均，其余（默认）= 几何平均。"""
    if name == "mean":
        return _arithmetic_mean(values)
    return _geometric_mean(values)


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

    aggregate = recipe.get("aggregate", "geomean")
    display_scale = recipe.get("display_scale")
    groups = _groups_of(recipe, suite_all)

    pick = recipe.get("pick")
    if recipe.get("combine"):
        group_rows = list(groups.values())
        return [
            _row_from_values(
                suite,
                recipe.get("label", suite),
                _aggregate([_group_value(g, pick, "baseline", aggregate) for g in group_rows], aggregate),
                _aggregate([_group_value(g, pick, "candidate", aggregate) for g in group_rows], aggregate),
                threshold_pct,
                display_scale=display_scale,
            )
        ]

    return [
        _make_suite_row(
            suite,
            "{0}（{1}）".format(suite, name),
            rows_in_group,
            pick,
            threshold_pct,
            aggregate,
            display_scale,
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
    aggregate = recipe.get("aggregate", "geomean")
    display_scale = recipe.get("display_scale")
    for label, items, higher_is_better in partition:
        if items is None:
            selected = [row for row in suite_all if row.item not in listed]
        else:
            selected = [row for row in suite_all if row.item in items]
        rows.append(
            _combined_row(
                suite, label, selected, threshold_pct, higher_is_better, aggregate, display_scale
            )
        )

    combine_all = recipe.get("combine_all")
    if combine_all is not None:
        rows.append(
            _combined_row(
                suite, combine_all, suite_all, threshold_pct, True, aggregate, display_scale
            )
        )
    return rows


def _combined_row(
    suite, label, selected, threshold_pct, higher_is_better, aggregate="geomean", display_scale=None
):
    return _row_from_values(
        suite,
        label,
        _combined_value(selected, "baseline", aggregate),
        _combined_value(selected, "candidate", aggregate),
        threshold_pct,
        higher_is_better,
        display_scale,
    )


def _combined_value(rows, side, aggregate="geomean"):
    """若干测试项合并成一个值：每个测试项内部先归并，再对各测试项的值归并。"""
    groups = {}
    for row in rows:
        groups.setdefault(row.item, []).append(row)
    return _aggregate(
        [_aggregate([getattr(row, side) for row in group], aggregate) for group in groups.values()],
        aggregate,
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


def _group_value(group_rows, pick, side, aggregate="geomean"):
    """一个分组的唯一值：取指定子项，或对该分组的子项**用原始值**归并。

    用原始值（不按方向取倒数）是需求方确认的口径；方向只用于判定劣化。
    """
    if pick is not None:
        return _pick_sub_item(group_rows, pick, side)
    return _aggregate([getattr(row, side) for row in group_rows], aggregate)


def _make_suite_row(
    suite, label, group_rows, pick, threshold_pct, aggregate="geomean", display_scale=None
):
    return _row_from_values(
        suite,
        label,
        _group_value(group_rows, pick, "baseline", aggregate),
        _group_value(group_rows, pick, "candidate", aggregate),
        threshold_pct,
        display_scale=display_scale,
    )


def _row_from_values(
    suite, label, base_value, cand_value, threshold_pct, higher_is_better=True, display_scale=None
):
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
        baseline_expr=_scale_expr(base_value, display_scale),
        candidate_expr=_scale_expr(cand_value, display_scale),
        higher_is_better=higher_is_better,
    )


def _scale_expr(value, display_scale):
    """按需求方要求把单位换算写成 Excel 公式、保留原值（决策 D19）。

    例：值为 116445015、换算系数 1000 → `=116445015/1000`。
    """
    if display_scale is None or value is None:
        return None
    return "={0}/{1}".format(_plain_number(value), _plain_number(display_scale))


def _plain_number(value):
    """整数不带小数点，便于公式可读（`116445015` 而非 `116445015.0`）。"""
    if float(value).is_integer():
        return str(int(value))
    return repr(value)


def _pick_sub_item(group_rows, sub_item, side):
    """取分组里指定子项的值；没有该子项则为 None（单边缺失或口径不适用）。"""
    for row in group_rows:
        if row.sub_item == sub_item:
            return getattr(row, side)
    return None
