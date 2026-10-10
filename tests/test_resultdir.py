"""resultdir 模块的行为规格。

测试只穿过约定的 seam：`perf_compare.resultdir.load`。
"""
import shutil
from pathlib import Path

import pytest

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


def test_加载结果目录_从nginx_json取出四个workload(tmp_path):
    """`nginx.json` 一条记录里带 `workload_data[]`，每个 workload 的 performance_data 是一个值。

    记录顶层的 performance_data（样例 234564.88）不使用 —— 汇总由四个 workload 自己算。
    """
    scenario_dir = tmp_path / "场景化测试"
    scenario_dir.mkdir()
    shutil.copy(str(FIXTURE / "场景化测试" / "nginx.json"), str(scenario_dir / "nginx.json"))

    results = load(str(tmp_path))

    assert results.value("nginx", "http_short", "") == 204025.72
    assert results.value("nginx", "http_long", "") == 407737.49
    assert results.value("nginx", "https_short", "") == 43473.1
    assert results.value("nginx", "https_long", "") == 249753.18


def test_加载结果目录_接入其余三个场景化套(tmp_path):
    """一次接入三个套的解析：flink_nexmark、redis_docker、mysql_sysbench。"""
    scenario_dir = tmp_path / "场景化测试"
    scenario_dir.mkdir()
    for name in ("flink_nexmark.json", "redis_docker.txt", "mysql_sysBench.txt"):
        shutil.copy(str(FIXTURE / "场景化测试" / name), str(scenario_dir / name))

    results = load(str(tmp_path))

    # flink_nexmark：每个 testcase 一条；performance_data 可能是字符串也可能是数字（事实 F7）
    assert results.value("flink_nexmark", "sum", "") == 3815.46
    assert results.value("flink_nexmark", "q0", "") == 211.88

    # redis_docker：只取 docker1..docker4，跳过文件自带的 avg / geom 两列
    assert results.value("redis_docker", "set", "docker1") == 145074.29
    assert results.value("redis_docker", "get", "docker4") == 74140.25

    # mysql_sysbench：每个测试项取 TPS 四次取值的平均（95th_latency 暂不显示）
    assert results.value("mysql_sysbench", "oltp_point_select", "TPS") == pytest.approx(126432.9)
    assert results.value("mysql_sysbench", "oltp_read_write", "TPS") == pytest.approx(6658.3325)


def test_加载结果目录_接入flink_wordcount与flink_6000c(tmp_path):
    """flink_wordcount：单条 JSON 记录，值可能是字符串。
    flink_6000c：三行 `"read-records": N,`，作为同一测试项的多次取值（末尾裸数字不参与）。
    """
    scenario_dir = tmp_path / "场景化测试"
    scenario_dir.mkdir()
    for name in ("flink_wordcount.json", "flink_6000c.txt"):
        shutil.copy(str(FIXTURE / "场景化测试" / name), str(scenario_dir / name))

    results = load(str(tmp_path))

    assert results.value("flink_wordcount", "flink", "") == 116445015.0

    assert results.value("flink_6000c", "read-records", "1") == 1749545840.0
    assert results.value("flink_6000c", "read-records", "2") == 1193304539.0
    assert results.value("flink_6000c", "read-records", "3") == 1839674039.0
    with pytest.raises(KeyError):
        results.value("flink_6000c", "read-records", "4")
