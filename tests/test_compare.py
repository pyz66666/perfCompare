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


def test_汇总口径_fio按每个测试项求几何平均再合并(tmp_path):
    """fio 的汇总值 = 每个测试项内部先求几何平均，再对所有测试项的值求几何平均。

    算例让两个测试项的项数不等，以区分「两步法」与「对全部子项一步求平均」：
      A = 1,1 → 几何平均 1；B = 10000 → 几何平均 10000；
      两步法 = √(1×10000) = 100；一步法 = (1×1×10000)^(1/3) ≈ 21.54。
    """
    for side in ("baseline", "candidate"):
        (tmp_path / side / "基础性能测试").mkdir(parents=True)
        (tmp_path / side / "基础性能测试" / "fio.txt").write_text(
            "read_iops_blocksize a b\naverage 1.0 1.0\nvariance 0.0 0.0\n"
            "write_iops_blocksize z\naverage 10000.0\nvariance 0.0\n",
            encoding="utf-8",
        )

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )

    rows = {row.label: row for row in comparison.suite_rows()}
    assert set(rows) == {"fio"}
    assert rows["fio"].baseline == pytest.approx(100.0, rel=1e-9)


def test_汇总口径_stream先按分组求几何平均再合并(tmp_path):
    """stream 的汇总值 = 单核四项的几何平均 与 多核四项的几何平均，再对两者求几何平均。

    算例刻意让两组项数不等，以便区分「两步法」与「对全部子项一步求平均」：
      单核 1,1,1 → 几何平均 1；多核 10000 → 几何平均 10000；
      两步法 = √(1×10000) = 100；若一步法对全部 4 项求平均则为 10。
    """
    for side in ("baseline", "candidate"):
        (tmp_path / side / "基础性能测试").mkdir(parents=True)
        (tmp_path / side / "基础性能测试" / "stream.txt").write_text(
            "1_Core a b c\naverage 1.0 1.0 1.0\nvariance 0.0 0.0 0.0\n"
            "384_Core z\naverage 10000.0\nvariance 0.0\n",
            encoding="utf-8",
        )

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )

    rows = {row.label: row for row in comparison.suite_rows()}
    assert set(rows) == {"stream"}
    assert rows["stream"].baseline == pytest.approx(100.0, rel=1e-9)


def test_汇总口径_unixbench直接取Index_Score并分单核多核两行(tmp_path):
    """unixbench 的汇总值就是工具自带的 System_Benchmarks_Index_Score，不再另算几何平均；
    且按单核/多核各出一行（需求方 2026-10-05）。期望值直接取自样例文件的对应子项。"""
    results = load(str(FIXTURE))

    comparison = compare(results, results, threshold_pct=5.0)

    by_label = {row.label: row for row in comparison.suite_rows()}
    assert set(by_label) == {
        "stream",
        "fio",
        "iozone3",
        "lmbench3",
        "netperf",
        "unixbench（单核）",
        "unixbench（多核）",
    }
    assert by_label["unixbench（单核）"].baseline == 1082.19
    assert by_label["unixbench（多核）"].baseline == 23032.61


def test_两版本测试项名不一致_列为单边缺失而不崩溃(tmp_path):
    """核数不同会让测试项名对不上（384_Core vs 256_Core）。不能崩溃，
    且两边各自独有的测试项都要被列出来，不能被静默忽略。"""
    for side, item in (("baseline", "384_Core"), ("candidate", "256_Core")):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        (target / "stream.txt").write_text(
            "{0} Copy\naverage 100.0\nvariance 0.0\n".format(item), encoding="utf-8"
        )

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )

    by_item = {row.item: row for row in comparison.rows()}
    assert set(by_item) == {"384_Core", "256_Core"}

    baseline_only = by_item["384_Core"]
    assert baseline_only.baseline == 100.0
    assert baseline_only.candidate is None
    assert baseline_only.pct is None
    assert baseline_only.degraded is False

    candidate_only = by_item["256_Core"]
    assert candidate_only.baseline is None
    assert candidate_only.candidate == 100.0
    assert candidate_only.pct is None
    assert candidate_only.degraded is False


def test_时延类指标变大_应判为劣化(tmp_path):
    """时延是「越小越好」：**变大**才是劣化。

    方向若一律按「越大越好」处理，时延上升会被判成没劣化 —— 这是会漏报的静默错误。
    此处把 lmbench3 的 Memory_latencies @ Main_mem 上调 20%（阈值 5%）。
    """
    for side in ("baseline", "candidate"):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        shutil.copy(str(FIXTURE / "基础性能测试" / "lmbench3.txt"), str(target / "lmbench3.txt"))

    path = tmp_path / "candidate" / "基础性能测试" / "lmbench3.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        parts = line.split()
        if parts and parts[0] == "Memory_latencies":
            position = parts[1:].index("Main_mem")
            average = lines[index + 1].split()
            average[position + 1] = repr(float(average[position + 1]) * 1.2)
            lines[index + 1] = " ".join(average)
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )

    row = [item for item in comparison.rows() if item.sub_item == "Main_mem"][0]
    assert row.pct == pytest.approx(20.0, rel=1e-9)
    assert row.degraded is True


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
