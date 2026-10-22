"""从结果目录自动识别「显示名」与「内核版本」，省去每次手填。

**显示名按两侧路径的差异推导**（不按层级约定去猜）：
两侧路径从第一个不同之处开始的部分，才是真正的版本差异。

    基线 …/950/openEuler-24.03/64K/基线版本
    对比 …/950/openEuler-24.03-SP1/64K/对比版本
    →   openEuler-24.03-64K / openEuler-24.03-SP1-64K

侧别目录（基线版本/对比版本/baseline…）只是「哪一侧」，推导时会从末尾剥掉。

**内核版本**从结果目录里 SPEC 报告的 `uname -a` / `SOFTWARE` 段读取。

配置里显式写了 `name` / `kernel_version` 时**以配置为准**（自动推导只作兜底）。
"""
import glob
import os
import re

# 侧别目录名：只表示「哪一侧」，不是版本信息，推导时要剥掉。
_SIDE_NAMES = frozenset(
    [
        "基线",
        "对比",
        "基线版本",
        "对比版本",
        "baseline",
        "candidate",
        "base",
        "compare",
        "before",
        "after",
        "old",
        "new",
    ]
)

# 差异部分只剩一级、且这一级本身很短（如 `4K`、`run1`）时，补一级公共前缀做上下文，
# 否则名字会只剩 `4K` 这种没头没脑的东西；而 `openEuler-24.03-64K` 已经够完整，不必再加料。
_MIN_DEPTH = 2
_THIN_WIDTH = 6

_SPEC_GLOB = "cpu2017_*.txt"
# `uname -a: Linux host 6.8.0-1014-kunpeng-devel-64k #14-...`
_UNAME_RE = re.compile(r"Linux\s+\S+\s+(\d+\.\d+[^\s]*)")
# `OS: Ubuntu 24.04.5 LTS` 的下一行是内核 release
_SOFTWARE_RE = re.compile(r"OS:[^\n]*\n\s*(\d+\.\d+[^\s]*)")


def derive_names(baseline_path, candidate_path):
    """按两侧路径的差异推导显示名，返回 (基线名, 对比名)。"""
    base_parts = _parts(baseline_path)
    cand_parts = _parts(candidate_path)

    common = 0
    while (
        common < len(base_parts)
        and common < len(cand_parts)
        and base_parts[common] == cand_parts[common]
    ):
        common += 1

    base_tail = base_parts[common:]
    cand_tail = cand_parts[common:]

    if not base_tail and not cand_tail:
        # 两侧是同一个目录 —— 没有差异可推，退回末级目录名（调用方会告警）。
        fallback = base_parts[-1] if base_parts else None
        return fallback, fallback

    # 一侧是另一侧的前缀（如 …/64K 与 …/64K/对比）：短的一侧用末级目录名补齐。
    if not base_tail:
        base_tail = base_parts[-1:]
    if not cand_tail:
        cand_tail = cand_parts[-1:]

    return (
        _join_with_context(base_tail, base_parts, common),
        _join_with_context(cand_tail, cand_parts, common),
    )


def derive_name(path):
    """只有一个路径时（无对照可比）的兜底：剥掉侧别目录后取末两级。"""
    parts = _parts(path)
    if not parts:
        return None
    tail = parts[-_MIN_DEPTH:]
    return "-".join(tail)


def derive_name(path):
    """单侧（无对照）时的兜底：剥掉侧别目录后取末两级。"""
    parts = _parts(path)
    if not parts:
        return None
    return "-".join(parts[-_MIN_DEPTH:])


def detect_kernel_version(path):
    """从结果目录里的 SPEC 报告读取内核版本；找不到返回 None。

    兼容平铺与「基础性能测试/」子目录两种布局。只读文件、不执行任何命令，
    内网离线环境同样可用。
    """
    for report_path in _spec_reports(path):
        try:
            with open(report_path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        matched = _UNAME_RE.search(text) or _SOFTWARE_RE.search(text)
        if matched:
            return matched.group(1)
    return None


def resolve_names(baseline, candidate=None):
    """返回 ((基线名, 对比名), (基线来源, 对比来源))；配置优先。

    `candidate` 为 None 时是**单侧整理**（没有对照可比），
    此时按「剥掉侧别名后取末两级」推导，对比名为 None。
    """
    if candidate is None:
        name = baseline.name or derive_name(baseline.path)
        return (name, None), ("配置" if baseline.name else "按目录路径推导", None)
    derived_base, derived_cand = derive_names(baseline.path, candidate.path)
    names = [derived_base, derived_cand]
    sources = ["按两侧路径差异推导", "按两侧路径差异推导"]
    for index, result_dir in enumerate((baseline, candidate)):
        if result_dir.name:
            names[index] = result_dir.name
            sources[index] = "配置"
    return tuple(names), tuple(sources)


def resolve_kernel(result_dir):
    """返回 (内核版本, 来源说明)；配置优先。"""
    if result_dir.kernel_version:
        return result_dir.kernel_version, "配置"
    detected = detect_kernel_version(result_dir.path)
    if detected:
        return detected, "读自 SPEC 报告"
    return None, "未找到"


def _parts(path):
    """切分路径并剥掉末尾的侧别目录。"""
    parts = [part for part in os.path.normpath(path).split(os.sep) if part and part != "."]
    if len(parts) > 1 and parts[-1].lower() in _SIDE_NAMES:
        parts = parts[:-1]
    return parts


def _join_with_context(tail, parts, common):
    """把差异部分连成名字；只剩一级「单薄」的名字时补一级公共前缀做上下文。"""
    if len(tail) < _MIN_DEPTH and common > 0 and _is_thin(tail[0]):
        tail = parts[common - 1 : common] + tail
    return "-".join(tail)


def _is_thin(component):
    """这一级名字本身信息量是否太少（短，或纯数字/页大小/run 编号）。"""
    return len(component) <= _THIN_WIDTH


def _spec_reports(path):
    found = sorted(glob.glob(os.path.join(path, _SPEC_GLOB)))
    if not found:
        found = sorted(glob.glob(os.path.join(path, "*", _SPEC_GLOB)))
    return found
