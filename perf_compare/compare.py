"""比对：把基线与一个对比结果目录逐 (套, 测试项, 子项) 比较，判定劣化。

差异百分比一律相对基线计算：(对比值 - 基线值) / 基线值 × 100。
"""
from dataclasses import dataclass
from typing import Optional

# 指标方向的默认值。首版接入的测试套（fio 长表项）全部是「越大越好」；
# 方向表与配置覆盖在 T6 落地（见 docs/plans/active/perf-compare-v1.md）。
_DEFAULT_DIRECTION_HIGHER_IS_BETTER = True


@dataclass(frozen=True)
class Row:
    """一个子项的比对面。"""

    suite: str
    item: str
    sub_item: str
    baseline: float
    candidate: float
    pct: Optional[float]
    degraded: bool


class Comparison:
    """一次比对的全部比对面。"""

    def __init__(self, rows):
        self._rows = list(rows)

    def rows(self):
        """按稳定顺序返回全部比对面。"""
        return list(self._rows)


def compare(baseline, candidate, threshold_pct):
    """比对基线与对比结果集，返回 Comparison。"""
    rows = []
    for suite, item, sub_item, base_value in baseline.observations():
        cand_value = candidate.value(suite, item, sub_item)
        # 基线为 0 时百分比无定义：真实数据里 lmbench3 的 RPC/UDP、RPC/TCP 就是 0.0。
        pct = None if base_value == 0 else (cand_value - base_value) / base_value * 100.0
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
    return Comparison(rows)


def _is_degraded(pct, threshold_pct):
    """劣化 = 朝变差的方向变化，且幅度严格大于阈值（决策记录 D15）。

    百分比无定义（基线为 0）时无从判定，一律不算劣化。
    """
    if pct is None:
        return False
    if _DEFAULT_DIRECTION_HIGHER_IS_BETTER:
        return -pct > threshold_pct
    return pct > threshold_pct
