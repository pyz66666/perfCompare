"""测试「自动识别显示名与内核版本」——省掉每次手填这两个字段。"""
import shutil
from pathlib import Path

from perf_compare.config import ResultDir
from perf_compare.identify import derive_name, detect_kernel_version, resolve

FIXTURE = Path(__file__).resolve().parent.parent / "测试结果模版"


def test_从目录路径推导显示名():
    """去掉侧别目录，取上面两级（OS + 页大小）。"""
    assert (
        derive_name("/home/AutoBench/report/950/openEuler-24.03/64K/基线版本")
        == "openEuler-24.03-64K"
    )
    assert (
        derive_name("/home/AutoBench/report/950/openEuler-24.03-SP1/64K/对比版本")
        == "openEuler-24.03-SP1-64K"
    )


def test_路径没有侧别目录时也推导正确():
    """直接把版本目录当结果目录（不带 基线版本/对比版本）也要能用。"""
    assert derive_name("/data/openEuler-24.03/64K") == "openEuler-24.03-64K"


def test_浅路径也给出可读名称且不报错():
    """层级不足时仍取「上面两级」，保留上级上下文；空路径返回 None。"""
    assert derive_name("/tmp/a") == "tmp-a"
    assert derive_name("") is None


def test_末级目录名恰好含old但并非侧别时不误判():
    """`golden` 含子串 `old`，不能因此被当成侧别目录删掉。"""
    assert derive_name("/data/golden/64K") == "golden-64K"


def test_从SPEC报告读取内核版本():
    """SPEC 报告里有 uname -a 与 SOFTWARE 段，可直接读到内核 release。"""
    assert (
        detect_kernel_version(str(FIXTURE / "基础性能测试"))
        == "6.8.0-1014-kunpeng-devel-64k"
    )


def test_没有SPEC报告时读不到内核版本(tmp_path):
    target = tmp_path / "结果"
    target.mkdir()
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(target / "fio.txt"))
    assert detect_kernel_version(str(target)) is None


def test_配置显式写了就以配置为准(tmp_path):
    """自动推导只作兜底，配置写了必须用配置的（不能悄悄覆盖用户意图）。"""
    result_dir = ResultDir(
        path="/home/AutoBench/report/950/openEuler-24.03/64K/基线版本",
        name="我的自定义名",
        kernel_version="6.6.0-自填",
    )
    name, kernel, sources = resolve(result_dir)

    assert name == "我的自定义名"
    assert kernel == "6.6.0-自填"
    assert sources == ("配置", "配置")


def test_未配置时自动推导并说明来源():
    result_dir = ResultDir(path=str(FIXTURE))

    name, kernel, sources = resolve(result_dir)

    assert name == "perf-compare-测试结果模版"
    assert kernel == "6.8.0-1014-kunpeng-devel-64k"
    assert sources == ("按目录路径推导", "读自 SPEC 报告")
