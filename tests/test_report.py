"""测试报告：结构完整、粒度正确，且**绝不泄露具体测量值**（这份报告对外公开）。"""
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
        comparison, str(tmp_path / "报告"), labels=("基线X", "对比Y"), info=INFO
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


def test_劣化程度用精确百分比(tmp_path):
    """劣化程度统一给精确百分比（不再有多种版本）。

    用子项明细（开关打开）验证两种幅度：-60% 判严重、-25% 判明显。
    """
    comparison = _造比较(tmp_path, {1: 0.40, 2: 0.75})

    txt_path, _ = write_report(
        comparison, str(tmp_path / "报告"), info=INFO, summarize_subitems=True
    )
    text = Path(txt_path).read_text(encoding="utf-8")

    assert "严重（60.00%）" in text
    assert "明显（25.00%）" in text


def test_html_带可视化图表与系统标识(tmp_path):
    comparison = _造比较(tmp_path, {1: 0.40})

    _, html_path = write_report(
        comparison, str(tmp_path / "报告"), labels=("基线X", "对比Y"), info=INFO
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
    """是否总结子项由开关控制，**默认关闭**（需求方 2026-10-19）。

    关闭时粒度退到「测试套」：连测试项名都不出现，也没有按套的图表；
    开启后清单到测试项，并额外给出「子项劣化汇总」。
    """
    comparison = _造比较(tmp_path, {1: 0.40, 2: 0.75})   # 同一测试项下两个子项劣化

    default_txt, default_html = write_report(comparison, str(tmp_path / "默认"), info=INFO)
    default = Path(default_txt).read_text(encoding="utf-8")
    assert "fio" in default
    assert "read_iops_blocksize" not in default       # 测试项名不出现
    assert "blocksize-4k" not in default              # 子项名不出现
    assert "子项劣化汇总" not in default
    assert "个子项" not in default                    # 不再提示子项个数
    assert "各测试套劣化项数" not in Path(default_html).read_text(encoding="utf-8")

    opened_txt, opened_html = write_report(
        comparison, str(tmp_path / "开启"), info=INFO, summarize_subitems=True
    )
    opened = Path(opened_txt).read_text(encoding="utf-8")
    assert "子项劣化汇总" in opened
    assert "read_iops_blocksize" in opened
    assert "blocksize-4k" in opened and "blocksize-16k" in opened
    opened_page = Path(opened_html).read_text(encoding="utf-8")
    assert "子项劣化汇总" in opened_page and "各测试套劣化项数" in opened_page


def test_分级按显示精度判定(tmp_path):
    """浮点误差 19.999999999999996 会显示成 20.00%，此时必须判「明显」而非「轻微」。

    分级与显示若用不同精度，就会出现「显示 20.00% 却是轻微」的自相矛盾。
    """
    for side, value in (("baseline", "1000"), ("candidate", "800.0000000000001")):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        (target / "fio.txt").write_text(
            "read_iops_blocksize 边界\naverage {0}\nvariance 0.0\n".format(value),
            encoding="utf-8",
        )
    comparison = compare(
        load(str(tmp_path / "baseline")), load(str(tmp_path / "candidate")), threshold_pct=5.0
    )

    txt_path, _ = write_report(comparison, str(tmp_path / "报告"), info=INFO, summarize_subitems=True)

    text = Path(txt_path).read_text(encoding="utf-8")
    assert "明显（20.00%）" in text
    assert "轻微（20.00%）" not in text


def test_无劣化时也能出报告(tmp_path):
    """两次相同数据 → 报告应写明「未发现劣化」，而不是空白或报错。"""
    comparison = _造比较(tmp_path, {})

    txt_path, html_path = write_report(comparison, str(tmp_path / "报告"), info=INFO)

    assert "未发现" in Path(txt_path).read_text(encoding="utf-8")
    assert "无劣化项" in Path(html_path).read_text(encoding="utf-8")
