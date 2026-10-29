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


def test_加载结果目录_结果文件平铺在目录里也能识别(tmp_path):
    """真实环境里结果文件**平铺**在结果目录下，没有 基础性能测试/ 之类的子目录。

    （样例模板按类别分了子目录，那只是为了便于查看；两种布局都要支持。）
    """
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(tmp_path / "fio.txt"))
    shutil.copy(str(FIXTURE / "基础性能测试" / "stream.txt"), str(tmp_path / "stream.txt"))
    shutil.copy(str(FIXTURE / "场景化测试" / "mysql_tpcc.txt"), str(tmp_path / "mysql_tpcc.txt"))

    results = load(str(tmp_path))

    assert results.value("fio", "read_iops_blocksize", "blocksize-4k") == 633106.3426
    assert results.value("mysql_tpcc", "tpmC", "") == 505267.31
    assert {suite for suite, _, _, _ in results.observations()} == {
        "fio",
        "stream",
        "mysql_tpcc",
    }


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


def test_加载结果目录_解析speccpu四份报告(tmp_path):
    """SPEC CPU2017 ASCII 报告：各 benchmark 的选中分数 + 汇总行。

    四份文件（int/fp × single/max）是**四个独立测试套**（需求方 2026-10-16）。
    汇总行标签按类：整数用 `SPECrate2017_int_base`、浮点用 `SPECrate2017_fp_base`。
    期望值取自文件（如 `500.perlbench_r  1  300  5.30  *`）。
    """
    base_dir = tmp_path / "基础性能测试"
    base_dir.mkdir()
    for name in (
        "cpu2017_int_single.txt",
        "cpu2017_int_max.txt",
        "cpu2017_fp_single.txt",
        "cpu2017_fp_max.txt",
    ):
        shutil.copy(str(FIXTURE / "基础性能测试" / name), str(base_dir / name))

    results = load(str(tmp_path))

    assert results.value("speccpu2017_int_single", "SPECrate2017_int_base", "") == 5.66
    assert results.value("speccpu2017_int_max", "SPECrate2017_int_base", "") == 896.0
    assert results.value("speccpu2017_fp_single", "SPECrate2017_fp_base", "") == 9.19
    assert results.value("speccpu2017_fp_max", "SPECrate2017_fp_base", "") == 849.0

    # 各 benchmark 的选中分数（行尾 `*`）
    assert results.value("speccpu2017_int_single", "500.perlbench_r", "") == 5.30
    assert results.value("speccpu2017_int_single", "557.xz_r", "") == 2.95
    assert results.value("speccpu2017_fp_single", "503.bwaves_r", "") == 46.2

    # 无效的 benchmark（fp_single 里 507.cactuBSSN_r 状态为 VE、分数为 NR）没有分数，
    # 不应伪造出数据 —— 这也是 INVALID RUN 的后果之一。
    with pytest.raises(KeyError):
        results.value("speccpu2017_fp_single", "507.cactuBSSN_r", "")


def test_文件名带不带前导空格都能识别(tmp_path):
    """样例里 unixbench 的文件名带一个前导空格，真实环境里通常没有。

    只认一种会整套漏读（用户实际踩到），必须两种都能找到。
    """
    target = tmp_path / "基础性能测试"
    target.mkdir()
    shutil.copy(
        str(FIXTURE / "基础性能测试" / " unixbench-master.txt"),
        str(target / "unixbench-master.txt"),      # 不带空格
    )

    results = load(str(tmp_path))

    suites = {suite for suite, _, _, _ in results.observations()}
    assert "unixbench" in suites


def test_文件名带前导空格时也仍然能识别(tmp_path):
    """样例原样（带空格）不能因为这次改动反而读不到。"""
    target = tmp_path / "基础性能测试"
    target.mkdir()
    shutil.copy(
        str(FIXTURE / "基础性能测试" / " unixbench-master.txt"),
        str(target / " unixbench-master.txt"),     # 带空格
    )

    results = load(str(tmp_path))

    suites = {suite for suite, _, _, _ in results.observations()}
    assert "unixbench" in suites


def test_加载结果目录_解析spark与spark_docker(tmp_path):
    """`spark.out` = 103 项 × 3 轮 + 1 个汇总（汇总值需 ÷3 得到单轮平均）；
    `spark_docker.out0/1/2` = 三个文件各代表一个 docker（一套多文件）。

    期望值直接取自样例文件：
    spark.out 的 [0]/[103]/[206] = 33.498/31.663/30.929；
    out0/out1/out2 的第 1 个值 = 24.92/14.981/23.628。
    """
    scenario_dir = tmp_path / "场景化测试"
    scenario_dir.mkdir()
    for name in ("spark.out", "spark_docker.out0", "spark_docker.out1", "spark_docker.out2"):
        shutil.copy(str(FIXTURE / "场景化测试" / name), str(scenario_dir / name))

    results = load(str(tmp_path))

    # spark：保留每轮，另给三轮平均
    assert results.value("spark", "native_q1", "轮1") == 33.498
    assert results.value("spark", "native_q1", "轮2") == 31.663
    assert results.value("spark", "native_q1", "轮3") == 30.929
    assert results.value("spark", "native_q1", "avg") == pytest.approx(32.03)

    # spark_docker：三个 docker 各一列 + 平均值
    assert results.value("spark_docker", "native_q1", "docker0") == 24.92
    assert results.value("spark_docker", "native_q1", "docker1") == 14.981
    assert results.value("spark_docker", "native_q1", "docker2") == 23.628
    assert results.value("spark_docker", "native_q1", "avg") == pytest.approx(21.176333333333336)


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
