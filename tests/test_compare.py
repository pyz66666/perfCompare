"""compare 模块的行为规格。

测试只穿过约定的 seam：`perf_compare.compare.compare`。
"""
import shutil
from pathlib import Path

import pytest

from perf_compare.compare import compare
from perf_compare.resultdir import load

FIXTURE = Path(__file__).resolve().parents[1] / "测试结果模版"


def _结果目录(tmp_path):
    base_dir = tmp_path / "基础性能测试"
    base_dir.mkdir()
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(base_dir / "fio.txt"))
    return load(str(tmp_path))


def test_同一结果目录作基线与对比_差异为零且无劣化(tmp_path):
    results = _结果目录(tmp_path)

    comparison = compare(results, results, threshold_pct=5.0)

    rows = comparison.rows()
    assert rows, "应当产出比对面"
    assert all(row.pct == 0.0 for row in rows)
    assert all(not row.degraded for row in rows)

    target = [
        row
        for row in rows
        if (row.suite, row.item, row.sub_item) == ("fio", "read_iops_blocksize", "blocksize-4k")
    ]
    assert len(target) == 1
    assert target[0].baseline == 633106.3426
    assert target[0].candidate == 633106.3426


def test_对比值下调百分之二十而阈值是五_该子项被判为劣化且其余不受影响(tmp_path):
    """A2 场景：把 fio 的 read_iops_blocksize @ blocksize-4k 下调 20%。"""
    baseline_dir = tmp_path / "baseline" / "基础性能测试"
    candidate_dir = tmp_path / "candidate" / "基础性能测试"
    baseline_dir.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)

    source = (FIXTURE / "基础性能测试" / "fio.txt").read_text(encoding="utf-8")
    (baseline_dir / "fio.txt").write_text(source, encoding="utf-8")

    lines = source.splitlines()
    # 第 1 行是 read_iops_blocksize 的表头，第 2 行是它的 average 行；第 2 列是 blocksize-4k。
    fields = lines[1].split()
    fields[1] = repr(float(fields[1]) * 0.8)
    lines[1] = " ".join(fields)
    (candidate_dir / "fio.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )

    degraded = [row for row in comparison.rows() if row.degraded]
    assert len(degraded) == 1
    assert (degraded[0].suite, degraded[0].item, degraded[0].sub_item) == (
        "fio",
        "read_iops_blocksize",
        "blocksize-4k",
    )
    # 期望值来自这个算例本身：下调 20%，故差异百分比为 -20%。
    assert degraded[0].pct == pytest.approx(-20.0, rel=1e-9)


def test_基线值为零_无法计算百分比且不判为劣化(tmp_path):
    """真实数据里 lmbench3 的 Local_latencies @ RPC/UDP 基线平均值就是 0.0，百分比无定义。"""
    base_dir = tmp_path / "基础性能测试"
    base_dir.mkdir()
    shutil.copy(str(FIXTURE / "基础性能测试" / "lmbench3.txt"), str(base_dir / "lmbench3.txt"))
    results = load(str(tmp_path))

    assert results.value("lmbench3", "Local_latencies", "RPC/UDP") == 0.0

    comparison = compare(results, results, threshold_pct=5.0)

    row = [item for item in comparison.rows() if item.sub_item == "RPC/UDP"][0]
    assert row.pct is None
    assert row.degraded is False
