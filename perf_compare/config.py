"""配置：从 JSON 文件读入基线、各对比结果目录与阈值。

用 JSON 而非 TOML/YAML：`tomllib` 到 Python 3.11 才进标准库，而本项目要兼容 3.8；
YAML 需要第三方依赖。见 docs/adr/0001-stdlib-only-plus-openpyxl.md。
"""
import json
from dataclasses import dataclass
from typing import List, Optional


class ConfigError(ValueError):
    """配置文件缺失或内容不合法。"""


@dataclass(frozen=True)
class ResultDir:
    """一个结果目录的引用。"""

    path: str
    kernel_version: Optional[str] = None


@dataclass(frozen=True)
class Config:
    """一次比对的全部输入。"""

    baseline: ResultDir
    candidates: List[ResultDir]
    threshold_pct: float


def load_config(path):
    """读取配置文件，返回 Config。"""
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    return Config(
        baseline=_result_dir(raw["baseline"]),
        candidates=[_result_dir(node) for node in raw["candidates"]],
        threshold_pct=float(raw["threshold_pct"]),
    )


def _result_dir(node):
    return ResultDir(path=node["path"], kernel_version=node.get("kernel_version"))
