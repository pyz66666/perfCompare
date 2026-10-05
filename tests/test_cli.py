"""cli 模块的行为规格（端到端）。

测试只穿过约定的 seam：`perf_compare.cli.main`。
"""
import json
import shutil
from pathlib import Path

from perf_compare.cli import main

FIXTURE = Path(__file__).resolve().parents[1] / "测试结果模版"


def test_命令行_读配置并写出对比表格(tmp_path):
    """一条命令跑通：配置 → 解析 → 比对 → 写出 xlsx。"""
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    (baseline / "基础性能测试").mkdir(parents=True)
    (candidate / "基础性能测试").mkdir(parents=True)

    source = (FIXTURE / "基础性能测试" / "fio.txt").read_text(encoding="utf-8")
    (baseline / "基础性能测试" / "fio.txt").write_text(source, encoding="utf-8")

    lines = source.splitlines()
    fields = lines[1].split()
    fields[1] = repr(float(fields[1]) * 0.8)
    lines[1] = " ".join(fields)
    (candidate / "基础性能测试" / "fio.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    config_path = tmp_path / "compare.json"
    config_path.write_text(
        json.dumps(
            {
                "baseline": {"path": str(baseline), "kernel_version": "6.6.0-72.3.0"},
                "candidates": [{"path": str(candidate), "kernel_version": "6.6.0-72.5.0"}],
                "threshold_pct": 5.0,
            }
        ),
        encoding="utf-8",
    )
    excel_path = tmp_path / "对比表格.xlsx"

    exit_code = main(["--config", str(config_path), "--excel", str(excel_path)])

    assert exit_code == 0
    assert excel_path.is_file()
