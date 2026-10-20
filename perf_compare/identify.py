"""从结果目录自动识别「显示名」与「内核版本」，省去每次手填。

这两项都能从现场信息推出来（需求方 2026-10-20 反馈手填太麻烦）：
- **显示名**：结果目录路径本身就带了 OS 与页大小，
  `/home/AutoBench/report/950/openEuler-24.03/64K/基线版本` → `openEuler-24.03-64K`
- **内核版本**：SPEC CPU2017 报告里 `uname -a` / `SOFTWARE` 段带内核 release

配置里显式写了 `name` / `kernel_version` 时**以配置为准**（自动推导只作兜底）。
"""
import glob
import os
import re

# 侧别目录名：推导显示名时要去掉这一级（它只表示「哪一侧」，不是版本信息）。
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

# 显示名取「侧别目录」之上两级（OS + 页大小）。
_NAME_DEPTH = 2

_SPEC_GLOB = "cpu2017_*.txt"
# `uname -a: Linux host 6.8.0-1014-kunpeng-devel-64k #14-...`
_UNAME_RE = re.compile(r"Linux\s+\S+\s+(\d+\.\d+[^\s]*)")
# `OS: Ubuntu 24.04.5 LTS` 的下一行是内核 release
_SOFTWARE_RE = re.compile(r"OS:[^\n]*\n\s*(\d+\.\d+[^\s]*)")


def derive_name(path):
    """从结果目录路径推导显示名；路径不可用时返回 None。

    例：`/home/AutoBench/report/950/openEuler-24.03/64K/基线版本` → `openEuler-24.03-64K`
    若最后一级不是侧别名（如直接把 `64K` 目录给出），则直接用最后两级。
    """
    parts = [part for part in os.path.normpath(path).split(os.sep) if part and part != "."]
    if not parts:
        return None
    if len(parts) > 1 and parts[-1].lower() in _SIDE_NAMES:
        parts = parts[:-1]
    tail = parts[-_NAME_DEPTH:]
    return "-".join(tail)


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


def resolve(result_dir):
    """返回 (显示名, 内核版本, 来源说明)；配置优先，缺失时自动推导。

    来源说明用于在终端打印「这个名字/版本是怎么来的」，便于当场核对。
    """
    name_source = "配置"
    name = result_dir.name
    if not name:
        name = derive_name(result_dir.path)
        name_source = "按目录路径推导" if name else "无法推导"

    kernel_source = "配置"
    kernel = result_dir.kernel_version
    if not kernel:
        kernel = detect_kernel_version(result_dir.path)
        kernel_source = "读自 SPEC 报告" if kernel else "未找到"

    return name, kernel, (name_source, kernel_source)


def _spec_reports(path):
    found = sorted(glob.glob(os.path.join(path, _SPEC_GLOB)))
    if not found:
        found = sorted(glob.glob(os.path.join(path, "*", _SPEC_GLOB)))
    return found
