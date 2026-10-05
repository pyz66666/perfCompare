"""excel 模块的行为规格。

测试只穿过约定的 seam：`perf_compare.excel.write_excel`；
读取产出文件用 openpyxl，因为 xlsx 本身就是对外契约。
"""
import shutil
from pathlib import Path

import openpyxl
import pytest

from perf_compare.compare import compare
from perf_compare.excel import write_excel
from perf_compare.resultdir import load

FIXTURE = Path(__file__).resolve().parents[1] / "测试结果模版"


def _劣化比对(tmp_path):
    """基线 = 样例数据；对比 = 样例数据里 fio 的 read_iops_blocksize @ blocksize-4k 下调 20%。"""
    baseline_dir = tmp_path / "baseline" / "基础性能测试"
    candidate_dir = tmp_path / "candidate" / "基础性能测试"
    baseline_dir.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)

    source = (FIXTURE / "基础性能测试" / "fio.txt").read_text(encoding="utf-8")
    (baseline_dir / "fio.txt").write_text(source, encoding="utf-8")

    lines = source.splitlines()
    fields = lines[1].split()
    fields[1] = repr(float(fields[1]) * 0.8)
    lines[1] = " ".join(fields)
    (candidate_dir / "fio.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )


def test_写出对比表格_首表是汇总且每个测试套一个子项明细表(tmp_path):
    comparison = _劣化比对(tmp_path)
    out_path = tmp_path / "对比表格.xlsx"

    write_excel(comparison, str(out_path))

    workbook = openpyxl.load_workbook(str(out_path))
    assert workbook.sheetnames[0] == "汇总"
    assert "fio" in workbook.sheetnames

    detail = workbook["fio"]
    assert [cell.value for cell in detail[1]] == [
        "测试项",
        "子项",
        "结果A",
        "结果B",
        "差距百分比",
        "是否劣化",
    ]
    detail_rows = [[cell.value for cell in row] for row in detail.iter_rows(min_row=2)]
    hit = [row for row in detail_rows if row[0] == "read_iops_blocksize" and row[1] == "blocksize-4k"]
    assert len(hit) == 1
    assert hit[0][3] is not None
    assert hit[0][4] == pytest.approx(-20.0, rel=1e-9)
    assert hit[0][5] == "是"

    summary = workbook["汇总"]
    assert [cell.value for cell in summary[1]] == ["测试套", "劣化项数", "总项数"]
    summary_rows = [[cell.value for cell in row] for row in summary.iter_rows(min_row=2)]
    fio_row = [row for row in summary_rows if row[0] == "fio"]
    assert len(fio_row) == 1
    assert fio_row[0][1] == 1
    assert fio_row[0][2] == len(detail_rows)


def test_写出对比表格_百分比无定义的子项显示为无法比较(tmp_path):
    """基线为 0 时留空白会被误读成漏数据，所以显式写出「无法比较」。"""
    for side in ("baseline", "candidate"):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        shutil.copy(
            str(FIXTURE / "基础性能测试" / "lmbench3.txt"), str(target / "lmbench3.txt")
        )

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )
    out_path = tmp_path / "对比表格.xlsx"

    write_excel(comparison, str(out_path))

    workbook = openpyxl.load_workbook(str(out_path))
    rows = [
        [cell.value for cell in row] for row in workbook["lmbench3"].iter_rows(min_row=2)
    ]
    hit = [row for row in rows if row[1] == "RPC/UDP"]
    assert len(hit) == 1
    assert hit[0][4] == "无法比较"
    assert hit[0][5] == "否"
