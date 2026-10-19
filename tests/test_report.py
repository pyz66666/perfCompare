"""测试报告：结构完整、三版本差异正确，且**绝不泄露具体测量值**（这份报告对外公开）。"""
import shutil
from pathlib import Path

from perf_compare.compare import compare
from perf_compare.report import write_report
from perf_compare.resultdir import load

FIXTURE = Path(__file__).resolve().parent.parent / "测试结果模版"
INFO = {
    "threshold_pct": 5.0,
    "baseline_kernel": "6.6.0-72.3.0",
    "candidate_kernel": "6.6.0-72.4.0",
    "baseline_commit": "aaa1111",
    "candidate_commit": "bbb2222",
}


def _造比较(tmp_path, factors):
    """造一份 fio 对比：把 average 行的指定列乘以系数（<1 → 劣化）。"""
    for side in ("baseline", "candidate"):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(target / "fio.txt"))

    path = tmp_path / "candidate" / "基础性能测试" / "fio.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    fields = lines[1].split()
    for column, factor in factors.items():
        fields[column] = repr(float(fields[column]) * factor)
    lines[1] = " ".join(fields)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return compare(
        load(str(tmp_path / "baseline")),
        load(str(tmp_path / "candidate")),
        threshold_pct=5.0,
    )


def test_报告不含任何具体测量值(tmp_path):
    """对外公开的报告里不能出现原始测量值 —— 连整数部分也不行。

    第 1 项劣化 -60%、第 2 项 -25%（阈值 5%）。
    """
    comparison = _造比较(tmp_path, {1: 0.40, 2: 0.75})

    txt_path, html_path = write_report(
        comparison, str(tmp_path / "报告"), labels=("基线X", "对比Y"), info=INFO, style=3
    )
    txt = Path(txt_path).read_text(encoding="utf-8")
    page = Path(html_path).read_text(encoding="utf-8")

    leaked = []
    for row in comparison.rows():
        for value in (row.baseline, row.candidate):
            if value is None or abs(value) < 100:
                continue
            for text in ("{:.0f}".format(value), "{:.4f}".format(value), repr(value)):
                for name, content in (("txt", txt), ("html", page)):
                    if text in content:
                        leaked.append((name, text))
    assert leaked == []


def test_三个版本的劣化程度表述不同(tmp_path):
    """V1 只有定性分级；V2 给区间；V3 给精确百分比。"""
    comparison = _造比较(tmp_path, {1: 0.40, 2: 0.75})   # -60%（严重）、-25%（明显）

    texts = {}
    for style in (1, 2, 3):
        txt_path, _ = write_report(
            comparison, str(tmp_path / "报告{0}".format(style)), info=INFO, style=style
        )
        texts[style] = Path(txt_path).read_text(encoding="utf-8")

    assert "严重" in texts[1] and "明显" in texts[1]
    assert "60.00%" not in texts[1] and ">30%" not in texts[1]      # 定性版不带任何量化
    assert ">30%" in texts[2] and "60.00%" not in texts[2]          # 分档版不给精确值
    assert "60.00%" in texts[3]                                     # 精确版给百分比


def test_html_带可视化图表与系统标识(tmp_path):
    comparison = _造比较(tmp_path, {1: 0.40})

    _, html_path = write_report(
        comparison, str(tmp_path / "报告"), labels=("基线X", "对比Y"), info=INFO, style=2
    )
    page = Path(html_path).read_text(encoding="utf-8")

    assert "<svg" in page                 # 内联图表，不依赖外部资源（内网可用）
    assert "http://" not in page and "https://" not in page
    assert "基线X" in page and "对比Y" in page
    assert "6.6.0-72.3.0" in page                  # 内核版本保留
    # 需求变更（2026-10-19）：系统标识里暂时隐藏 commitId 与报告版本
    assert "bbb2222" not in page and "aaa1111" not in page
    assert "CommitId" not in page and "报告版本" not in page


def test_默认不展开子项_开启后才总结子项(tmp_path):
    """需求方 2026-10-19：是否总结子项由开关控制，**默认关闭**。

    关闭时报告只到「测试套 / 测试项」，子项名不出现；开启后额外给出「子项劣化汇总」。
    """
    comparison = _造比较(tmp_path, {1: 0.40, 2: 0.75})   # 同一测试项下两个子项劣化

    default_txt, _ = write_report(comparison, str(tmp_path / "默认"), info=INFO, style=2)
    default = Path(default_txt).read_text(encoding="utf-8")
    assert "read_iops_blocksize" in default          # 测试项在
    assert "blocksize-4k" not in default             # 子项名不出现（默认关闭）
    assert "子项劣化汇总" not in default

    opened_txt, opened_html = write_report(
        comparison, str(tmp_path / "开启"), info=INFO, style=2, summarize_subitems=True
    )
    opened = Path(opened_txt).read_text(encoding="utf-8")
    assert "子项劣化汇总" in opened
    assert "blocksize-4k" in opened and "blocksize-16k" in opened
    assert "子项劣化汇总" in Path(opened_html).read_text(encoding="utf-8")


def test_无劣化时也能出报告(tmp_path):
    """两次相同数据 → 报告应写明「未发现劣化」，而不是空白或报错。"""
    comparison = _造比较(tmp_path, {})

    txt_path, html_path = write_report(comparison, str(tmp_path / "报告"), info=INFO, style=2)

    assert "未发现" in Path(txt_path).read_text(encoding="utf-8")
    assert "无劣化项" in Path(html_path).read_text(encoding="utf-8")
