"""excel 模块的行为规格。

测试只穿过约定的 seam：`perf_compare.excel.write_excel`；
读取产出文件用 openpyxl，因为 xlsx 本身就是对外契约。

工作簿布局（需求方 2026-10-05 修正）：
- 「汇总」       —— 套级唯一值的对比（不是劣化项计数）
- 「子项劣化汇总」 —— 跨套列出被判定劣化的子项
- 每个测试套一个 sheet —— 该套全部子项的明细
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


def test_写出对比表格_首表是套级汇总且每个测试套一个子项明细表(tmp_path):
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
    # 表头是 A–E 五列；F1 上是套级口径的显著标注（见下一个测试）。
    assert [cell.value for cell in summary[1]][:5] == [
        "测试套",
        "结果A",
        "结果B",
        "差距百分比",
        "是否劣化",
    ]
    summary_rows = [[cell.value for cell in row] for row in summary.iter_rows(min_row=2)]
    # 每个测试套恰好一行套级结果
    assert [row[0] for row in summary_rows] == ["fio"]


def test_写出对比表格_子项劣化汇总表只列被判为劣化的子项(tmp_path):
    comparison = _劣化比对(tmp_path)
    out_path = tmp_path / "对比表格.xlsx"

    write_excel(comparison, str(out_path))

    workbook = openpyxl.load_workbook(str(out_path))
    assert "子项劣化汇总" in workbook.sheetnames

    sheet = workbook["子项劣化汇总"]
    assert [cell.value for cell in sheet[1]] == [
        "测试套",
        "测试项",
        "子项",
        "结果A",
        "结果B",
        "差距百分比",
    ]
    rows = [[cell.value for cell in row] for row in sheet.iter_rows(min_row=2)]
    assert len(rows) == 1
    assert rows[0][:3] == ["fio", "read_iops_blocksize", "blocksize-4k"]
    assert rows[0][5] == pytest.approx(-20.0, rel=1e-9)


def _扰动(path, item, sub, factor):
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        parts = line.split()
        if parts and parts[0] == item:
            position = parts[1:].index(sub)
            average = lines[index + 1].split()
            average[position + 1] = repr(float(average[position + 1]) * factor)
            lines[index + 1] = " ".join(average)
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_写出对比表格_差距百分比保留两位小数(tmp_path):
    """0.92 倍就是精确的 -8%，但浮点会算成 -7.999999999999999，交付物里必须写成 -8.0。"""
    for side in ("baseline", "candidate"):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        shutil.copy(
            str(FIXTURE / "基础性能测试" / "stream.txt"), str(target / "stream.txt")
        )
    _扰动(tmp_path / "candidate" / "基础性能测试" / "stream.txt", "384_Core", "Copy", 0.92)

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )
    out_path = tmp_path / "对比表格.xlsx"

    write_excel(comparison, str(out_path))

    workbook = openpyxl.load_workbook(str(out_path))
    rows = [[cell.value for cell in row] for row in workbook["stream"].iter_rows(min_row=2)]
    hit = [row for row in rows if row[0] == "384_Core" and row[1] == "Copy"]
    assert len(hit) == 1
    assert hit[0][4] == -8.0


def test_写出对比表格_汇总表的套级唯一值取子项几何平均(tmp_path):
    """合成样例便于独立验算：套内两个子项 100 与 400，几何平均为 √(100×400)=200；
    对比侧改成 100 与 100，几何平均为 100；故套级差距 = (100−200)/200 = −50%。
    """
    for side in ("baseline", "candidate"):
        (tmp_path / side / "基础性能测试").mkdir(parents=True)
    (tmp_path / "baseline" / "基础性能测试" / "stream.txt").write_text(
        "1_Core a b\naverage 100.0 400.0\nvariance 0.0 0.0\n", encoding="utf-8"
    )
    (tmp_path / "candidate" / "基础性能测试" / "stream.txt").write_text(
        "1_Core a b\naverage 100.0 100.0\nvariance 0.0 0.0\n", encoding="utf-8"
    )

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )
    out_path = tmp_path / "对比表格.xlsx"

    write_excel(comparison, str(out_path))

    summary = openpyxl.load_workbook(str(out_path))["汇总"]
    rows = [[cell.value for cell in row] for row in summary.iter_rows(min_row=2)]
    stream_row = [row for row in rows if row[0] == "stream"][0]
    # 几何平均在对数域计算（避免大数值连乘溢出），故会有极小浮点尾差，
    # 用紧容差断言：200 = √(100×400)、100、-50% 这几个值本身是算例给的。
    assert stream_row[1] == pytest.approx(200.0, rel=1e-12)
    assert stream_row[2] == pytest.approx(100.0, rel=1e-12)
    assert stream_row[3] == pytest.approx(-50.0, rel=1e-9)
    assert stream_row[4] == "是"
    # 算法未经需求方确认，必须在表里显著标注，不能被当成权威数字读走。
    assert "未确认" in str(summary["F1"].value)


def test_写出对比表格_套级几何平均不会因数值过大而溢出(tmp_path):
    """fio 有 96 个子项、量级约 1e5，朴素连乘会溢出成 inf，而 Excel 存不下 inf（读回来是空值）。
    算例：两个 1e300，几何平均应为 1e300。
    """
    for side in ("baseline", "candidate"):
        (tmp_path / side / "基础性能测试").mkdir(parents=True)
        (tmp_path / side / "基础性能测试" / "stream.txt").write_text(
            "1_Core a b\naverage 1e300 1e300\nvariance 0.0 0.0\n", encoding="utf-8"
        )

    comparison = compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )
    out_path = tmp_path / "对比表格.xlsx"

    write_excel(comparison, str(out_path))

    summary = openpyxl.load_workbook(str(out_path))["汇总"]
    rows = list(summary.iter_rows(min_row=2, values_only=True))
    stream_row = [row for row in rows if row[0] == "stream"][0]
    assert stream_row[1] == pytest.approx(1e300, rel=1e-9)
    assert stream_row[2] == pytest.approx(1e300, rel=1e-9)


def test_写出对比表格_单边缺失的测量项显式标注而不是留空白(tmp_path):
    """核数不同会让项名对不上（384_Core vs 256_Core），缺失的一侧要写明「缺失」。"""
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
    out_path = tmp_path / "对比表格.xlsx"

    write_excel(comparison, str(out_path))

    rows = [
        [cell.value for cell in row]
        for row in openpyxl.load_workbook(str(out_path))["stream"].iter_rows(min_row=2)
    ]
    by_item = {row[0]: row for row in rows}
    assert by_item["384_Core"][2] == 100.0
    assert by_item["384_Core"][3] == "缺失"
    assert by_item["256_Core"][2] == "缺失"
    assert by_item["256_Core"][3] == 100.0


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
