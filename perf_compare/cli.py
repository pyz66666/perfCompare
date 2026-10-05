"""命令行入口：装配配置、结果目录加载、比对与写出。

用法：
    python3 -m perf_compare --config compare.json --excel 对比表格.xlsx
"""
import argparse
import sys

from .compare import compare
from .config import load_config
from .excel import write_excel
from .resultdir import load


def main(argv=None):
    """执行一次比对，返回进程退出码。"""
    parser = argparse.ArgumentParser(
        prog="perf-compare",
        description="把多次性能测试的结果目录横向比对，判定劣化并产出对比表格。",
    )
    parser.add_argument("--config", required=True, help="配置文件路径（JSON）")
    parser.add_argument("--excel", required=True, help="对比表格输出路径（.xlsx）")
    args = parser.parse_args(argv)

    config = load_config(args.config)

    # 多对比结果目录时，Excel 的行列该如何组织尚未确定（阻塞项 O8），
    # 因此首版只接受恰好一个对比目录，而不是自行发明一种布局。
    if len(config.candidates) != 1:
        print(
            "首版只支持恰好一个对比结果目录，配置里给了 %d 个。" % len(config.candidates),
            file=sys.stderr,
        )
        return 2

    baseline = load(config.baseline.path)
    candidate = load(config.candidates[0].path)
    comparison = compare(baseline, candidate, config.threshold_pct)
    write_excel(comparison, args.excel)
    return 0
