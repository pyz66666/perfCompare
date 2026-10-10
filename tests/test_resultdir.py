"""resultdir 模块的行为规格。

测试只穿过约定的 seam：`perf_compare.resultdir.load`。
"""
import shutil
from pathlib import Path

from perf_compare.resultdir import load

FIXTURE = Path(__file__).resolve().parents[1] / "测试结果模版"


def test_加载结果目录_解析长表格式的测试项与子项(tmp_path):
    """fio.txt 是「长表」格式：首行是测试项名 + 各子项标签，随后 average / variance 两行。

    断言值取自 average 行而非 variance 行 —— 同一列上两者量级不同
    （average 为 633106.3426，variance 为 11328502.574447），可分辨是否读错行。
    """
    base_dir = tmp_path / "基础性能测试"
    base_dir.mkdir()
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(base_dir / "fio.txt"))

    results = load(str(tmp_path))

    assert results.value("fio", "read_iops_blocksize", "blocksize-4k") == 633106.3426


# 长表族的全部基础套文件。注意 unixbench 的文件名带一个前导空格。
长表族文件 = [
    "stream.txt",
    "netperf.txt",
    "iozone3.txt",
    "lmbench3.txt",
    "fio.txt",
    " unixbench-master.txt",
]


def test_加载结果目录_覆盖长表族的六个基础测试套(tmp_path):
    base_dir = tmp_path / "基础性能测试"
    base_dir.mkdir()
    for name in 长表族文件:
        shutil.copy(str(FIXTURE / "基础性能测试" / name), str(base_dir / name))

    results = load(str(tmp_path))

    assert {suite for suite, _, _, _ in results.observations()} == {
        "stream",
        "netperf",
        "iozone3",
        "lmbench3",
        "fio",
        "unixbench",
    }
    # 断言 unixbench 能解析，钉住带前导空格文件名这个坑。
    assert (
        results.value(
            "unixbench", "Index_Values_1core", "Dhrystone_2_using_register_variables"
        )
        == 4634.3343
    )


def test_加载结果目录_从日志里取出mysql_tpcc的tpmC(tmp_path):
    """`mysql_tpcc.txt` 只有一行日志，值要按正则从 `Measured tpmC (NewOrders) = <值>` 取。"""
    scenario_dir = tmp_path / "场景化测试"
    scenario_dir.mkdir()
    shutil.copy(
        str(FIXTURE / "场景化测试" / "mysql_tpcc.txt"), str(scenario_dir / "mysql_tpcc.txt")
    )

    results = load(str(tmp_path))

    assert results.value("mysql_tpcc", "tpmC", "") == 505267.31
