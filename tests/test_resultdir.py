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
