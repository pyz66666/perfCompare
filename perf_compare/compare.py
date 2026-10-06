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
    """一个测试套的套级比对面。"""

    suite: str
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
                degraded=_is_degraded(pct, threshold_pct),
            )
        )
    return Comparison(rows, _suite_level(rows, threshold_pct))


def _is_degraded(pct, threshold_pct):
    """劣化 = 朝变差的方向变化，且幅度严格大于阈值（决策记录 D15）。

    百分比无定义（基线为 0）时无从判定，一律不算劣化。
    """
    if pct is None:
        return False
    return -pct > threshold_pct


# 「越小越好」的测试项。这是一个**临时口径**：完整的方向表与配置覆盖属于 T6，
# 尚未实现，因此这里只列出当前已接入的测试套里已知的延迟类测试项。
_LOWER_IS_BETTER_ITEMS = ("Processor_Processes", "Context_switching_ctxsw")


def _higher_is_better(item):
    if "latenc" in item.lower():
        return False
    return item not in _LOWER_IS_BETTER_ITEMS


def _normalized(value, higher_is_better):
    """把测量值换算成「越大越好」的口径，供几何平均使用。

    几何平均要求正数；单边缺失（None）与 0 值一律排除，不参与套级归并。
    """
    if value is None or value <= 0:
        return None
    return value if higher_is_better else 1.0 / value


def _geometric_mean(values):
    """在对数域求几何平均。

    朴素连乘在这类数据上必然出事：fio 有 96 个子项、量级约 1e5，乘积约 1e480 会溢出成
    inf，而 Excel 存不下 inf（读回来是空值）。对数域没有这个问题。
    """
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return math.exp(sum(math.log(value) for value in usable) / len(usable))


def _suite_level(rows, threshold_pct):
    """套级唯一值 = 套内全部子项（按方向归一化后）的几何平均，先合并再比。

    **该算法未经需求方确认（阻塞项 O1）**，属临时口径；需求方提供算法后只需改这里。
    """
    suite_rows = []
    for suite in dict.fromkeys(row.suite for row in rows):
        base_values = []
        cand_values = []
        for row in rows:
            if row.suite != suite:
                continue
            higher_is_better = _higher_is_better(row.item)
            base_values.append(_normalized(row.baseline, higher_is_better))
            cand_values.append(_normalized(row.candidate, higher_is_better))

        base_value = _geometric_mean(base_values)
        cand_value = _geometric_mean(cand_values)
        pct = None
        if base_value is not None and cand_value is not None and base_value != 0:
            pct = (cand_value - base_value) / base_value * 100.0
        suite_rows.append(
            SuiteRow(
                suite=suite,
                baseline=base_value,
                candidate=cand_value,
                pct=pct,
                degraded=_is_degraded(pct, threshold_pct),
            )
        )
    return suite_rows
