"""测试「自动识别显示名与内核版本」——省掉每次手填这两个字段。

显示名按**两侧路径的差异**推导，而不是按层级约定去猜：
两侧路径从第一个不同之处开始的部分，才是真正的版本差异。
"""
import shutil
from pathlib import Path

from perf_compare.config import ResultDir
from perf_compare.identify import (
    derive_names,
    detect_kernel_version,
    resolve_kernel,
    resolve_names,
)

FIXTURE = Path(__file__).resolve().parent.parent / "测试结果模版"

BASE = "/home/AutoBench/report/950/openEuler-24.03/64K/基线版本"
CAND = "/home/AutoBench/report/950/openEuler-24.03-SP1/64K/对比版本"


def test_按两侧差异推导显示名():
    """典型布局：只有 OS 版本那一级不同。"""
    assert derive_names(BASE, CAND) == ("openEuler-24.03-64K", "openEuler-24.03-SP1-64K")


def test_侧目录带后缀也能剥掉():
    """`对比版本1`、`baseline-2` 这类带后缀的侧目录，同样不该进名字。"""
    assert derive_names(
        "/r/950/openEuler-24.03/64K/基线版本",
        "/r/950/openEuler-24.03-SP1/64K/对比版本1",
    ) == ("openEuler-24.03-64K", "openEuler-24.03-SP1-64K")
    assert derive_names(
        "/r/950/openEuler-24.03/64K/baseline-2",
        "/r/950/openEuler-24.03-SP1/64K/candidate-3",
    ) == ("openEuler-24.03-64K", "openEuler-24.03-SP1-64K")


def test_golden不被误判为侧别目录():
    """`golden` 含 old 但不是侧别目录 —— 前缀/精确匹配都要避免误伤。"""
    assert derive_names("/r/a/golden/64K", "/r/b/golden/64K") == ("a-golden-64K", "b-golden-64K")


def test_中间夹了日期目录也能推对():
    """旧实现按「最后两级」取，会得到 `64K-2026-10-01`；按差异推导不受影响。"""
    base = "/r/950/openEuler-24.03/64K/2026-10-01/基线"
    cand = "/r/950/openEuler-24.03-SP1/64K/2026-10-02/对比"
    assert derive_names(base, cand) == (
        "openEuler-24.03-64K-2026-10-01",
        "openEuler-24.03-SP1-64K-2026-10-02",
    )


def test_侧目录命名不规范也能推对():
    """侧目录叫 base_1 / A 之类，仍以「第一个不同之处」为准。"""
    assert derive_names(
        "/r/950/openEuler-24.03/64K/base_1", "/r/950/openEuler-24.03-SP1/64K/A"
    ) == ("openEuler-24.03-64K-base_1", "openEuler-24.03-SP1-64K-A")


def test_只差页大小时补一级上下文():
    """差异只有 `4K` / `64K` 时，名字太单薄，需要补上一级 OS 做上下文。"""
    assert derive_names("/r/950/openEuler-24.03/4K/基线", "/r/950/openEuler-24.03/64K/对比") == (
        "openEuler-24.03-4K",
        "openEuler-24.03-64K",
    )


def test_没有侧目录时直接用差异部分():
    assert derive_names(
        "/home/AutoBench/result/openEuler-24.03-64K",
        "/home/AutoBench/result/openEuler-24.03-SP1-64K",
    ) == ("openEuler-24.03-64K", "openEuler-24.03-SP1-64K")


def test_两侧路径完全相同时给出同名():
    """自比对时无从推导差异，退回末级目录名（调用方会因此告警）。"""
    assert derive_names("/r/a/64K", "/r/a/64K") == ("64K", "64K")


def test_一侧是另一侧前缀时不崩溃():
    names = derive_names("/r/950/64K", "/r/950/64K/对比")
    assert len(names) == 2 and all(names)


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


def test_内核版本配置优先(tmp_path):
    configured = ResultDir(path=str(FIXTURE), kernel_version="6.6.0-自填")
    kernel, source = resolve_kernel(configured)
    assert kernel == "6.6.0-自填"
    assert source == "配置"

    auto = ResultDir(path=str(FIXTURE / "基础性能测试"))
    kernel, source = resolve_kernel(auto)
    assert kernel == "6.8.0-1014-kunpeng-devel-64k"
    assert source == "读自 SPEC 报告"


def test_显示名配置优先():
    """配置里写了 name 就必须用配置的，不能被自动推导覆盖。"""
    base = ResultDir(path=BASE, name="我的自定义名")
    cand = ResultDir(path=CAND)

    names, sources = resolve_names(base, cand)

    assert names[0] == "我的自定义名"
    assert names[1] == "openEuler-24.03-SP1-64K"
    assert sources == ("配置", "按两侧路径差异推导")
