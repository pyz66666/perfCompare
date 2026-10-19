"""命令行入口：装配配置、结果目录加载、比对与写出。

用法：
    python3 -m perf_compare --config compare.json --excel 对比表格.xlsx

出错时把**完整堆栈追加写入日志文件**（默认 `logs/perf-compare.log`，可用 `--log-dir` 改），
终端上只提示日志路径。终端信息一闪而过，日志才留得住，便于以后排查。
"""
import argparse
import datetime
import os
import sys
import traceback

from .compare import compare
from .config import load_config
from .excel import write_excel
from .report import write_report
from .resultdir import load_with_report

LOG_FILE_NAME = "perf-compare.log"
DEFAULT_LOG_DIR = "logs"


def main(argv=None):
    """执行一次比对，返回进程退出码。"""
    args = _build_parser().parse_args(argv)
    try:
        return _run(args)
    except Exception:
        log_path = _write_error_log(args.log_dir, argv)
        print("执行失败，详细堆栈已写入日志：{0}".format(log_path), file=sys.stderr)
        return 1


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="perf-compare",
        description="把多次性能测试的结果目录横向比对，判定劣化并产出对比表格。",
    )
    parser.add_argument("--config", required=True, help="配置文件路径（JSON）")
    parser.add_argument("--excel", required=True, help="对比表格输出路径（.xlsx）")
    parser.add_argument(
        "--report",
        help="测试报告输出前缀（可选）：写出 <前缀>.txt 与 <前缀>.html",
    )
    parser.add_argument(
        "--summarize-subitems",
        action="store_true",
        help="在报告中总结子项（默认关闭：只列到测试项级别）",
    )
    parser.add_argument(
        "--log-dir", default=DEFAULT_LOG_DIR, help="报错日志目录（默认 logs/）"
    )
    return parser


def _run(args):
    config = load_config(args.config)

    # 多个对比结果目录时 Excel 的行列该怎么组织尚未确定（阻塞项 O8），
    # 因此首版只接受恰好一个对比目录，而不是自行发明一种布局。
    if len(config.candidates) != 1:
        print(
            "首版只支持恰好一个对比结果目录，配置里给了 %d 个。" % len(config.candidates),
            file=sys.stderr,
        )
        return 2

    baseline_path = config.baseline.path
    candidate_path = config.candidates[0].path
    # 两侧是同一个目录时，结果必然全为 0 —— 那是最危险的假结论（看起来「毫无劣化」）。
    _同一个目录(baseline_path, candidate_path)
    baseline, baseline_report = load_with_report(baseline_path)
    candidate, candidate_report = load_with_report(candidate_path)

    # 主动交代「读到什么、缺什么」—— 结果目录里缺失的套会被静默跳过，
    # 不打印出来的话，用户无从判断是数据不全、路径填错，还是文件格式变了。
    _report_read(baseline_path, baseline_report, "基线")
    _report_read(candidate_path, candidate_report, "对比")

    comparison = compare(baseline, candidate, config.threshold_pct)
    rows = comparison.rows()

    if not rows:
        # 退出码 0 + 空表是最危险的失败方式：用户会以为跑成功了。
        print(
            "两个结果目录里没有读到任何测试套，未生成表格。\n"
            "请检查配置里的 path 是否指向「结果目录」本身 ——\n"
            "该目录下应当直接放着结果文件（如 fio.txt、stream.txt、mysql_tpcc.txt）。",
            file=sys.stderr,
        )
        return 3

    excluded = comparison.excluded_suites()
    if excluded:
        # 只在一侧存在的套不参与对比，但必须说明，不能静默不出现。
        print(
            "只在一侧出现、未纳入对比的测试套：{0}（只比对两侧都包含的套）".format(excluded)
        )

    # 两侧数据一模一样（拷贝、或路径填成同一处）时，全 0 的表会被误读成「没有劣化」。
    if all(row.pct in (0, None) for row in rows):
        print(
            "    ⚠ 两侧数据完全一致（所有子项差距都是 0）—— 请确认两个 path 是否指向了同一份数据。"
        )

    write_excel(
        comparison,
        args.excel,
        _显示名(config),
        {
            "baseline_path": baseline_path,
            "candidate_path": candidate_path,
            "threshold_pct": config.threshold_pct,
            "excluded_suites": excluded,
        },
    )
    if args.report:
        txt_path, html_path = write_report(
            comparison,
            args.report,
            _显示名(config),
            {
                "threshold_pct": config.threshold_pct,
                "baseline_kernel": config.baseline.kernel_version,
                "candidate_kernel": config.candidates[0].kernel_version,
                "baseline_commit": config.baseline.commit_id,
                "candidate_commit": config.candidates[0].commit_id,
            },
            summarize_subitems=args.summarize_subitems,
        )
        print(
            "已写出测试报告：{0}、{1}（不含测量值）".format(txt_path, html_path)
        )

    print(
        "已写出对比表格：{0}（比对面 {1} 条，单边缺失 {2} 条，劣化 {3} 条）".format(
            args.excel,
            len(rows),
            sum(1 for row in rows if row.baseline is None or row.candidate is None),
            sum(1 for row in rows if row.degraded),
        )
    )
    return 0


def _同一个目录(baseline_path, candidate_path):
    """两侧解析到同一个真实目录时告警（含末尾斜杠、相对路径等写法差异）。"""
    if os.path.realpath(baseline_path) == os.path.realpath(candidate_path):
        print(
            "    ⚠ 基线与对比指向**同一个目录**（{0}），结果必然全为 0 —— 请检查配置里的两个 path。"
            .format(baseline_path)
        )


def _显示名(config):
    """表头用的两侧名称；配置里没写就用「结果A／结果B」（需求方 2026-10-12）。"""
    return (
        config.baseline.name or "结果A",
        config.candidates[0].name or "结果B",
    )


def _report_read(directory, report, label):
    """打印某一侧读到哪些套、哪些文件在但解析不出数据、哪些文件没找到。

    区分「文件不在」与「文件在但解析不出数据」很重要：前者是没测或命名不同，
    后者是格式变了 —— 笼统说「未找到」会让用户无法定位。
    """
    read = [suite for suite, _, count, _, _ in report if count > 0]
    empty = [
        os.path.basename(path)
        for _, path, count, _, _ in report
        if path is not None and count == 0
    ]
    absent = [suite for suite, path, _, _, _ in report if path is None]

    print("{0} {1}：读到 {2} 个测试套 {3}".format(label, directory, len(read), read))
    if empty:
        print("    文件在、但没解析出数据（可能是格式不符）：{0}".format(empty))
    if absent:
        print("    未找到（未测或命名不同）：{0}".format(absent))

    # 结果文件里的告警标记（如 INVALID RUN，其汇总值不可报告），按提示文案归并后打印。
    by_note = {}
    for suite, _, _, _, notes in report:
        for note in notes:
            by_note.setdefault(note, []).append(suite)
    for note in sorted(by_note):
        print("    ⚠ {0}：{1}".format(note, sorted(by_note[note])))


def _write_error_log(log_dir, argv):
    """把当前异常堆栈追加写入日志，返回日志文件路径。"""
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    path = os.path.join(log_dir, LOG_FILE_NAME)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("=" * 70 + "\n")
        handle.write(
            "时间：{0}\n".format(datetime.datetime.now().isoformat(timespec="seconds"))
        )
        handle.write("参数：{0}\n".format(sys.argv[1:] if argv is None else argv))
        traceback.print_exc(file=handle)
    return path
