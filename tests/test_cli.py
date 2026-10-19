"""cli 模块的行为规格（端到端）。

测试只穿过约定的 seam：`perf_compare.cli.main`。
"""
import json
import shutil
from pathlib import Path

import openpyxl

from perf_compare.cli import main

FIXTURE = Path(__file__).resolve().parents[1] / "测试结果模版"


def test_命令行_读配置并写出对比表格(tmp_path):
    """一条命令跑通：配置 → 解析 → 比对 → 写出 xlsx。"""
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    (baseline / "基础性能测试").mkdir(parents=True)
    (candidate / "基础性能测试").mkdir(parents=True)

    source = (FIXTURE / "基础性能测试" / "fio.txt").read_text(encoding="utf-8")
    (baseline / "基础性能测试" / "fio.txt").write_text(source, encoding="utf-8")

    lines = source.splitlines()
    fields = lines[1].split()
    fields[1] = repr(float(fields[1]) * 0.8)
    lines[1] = " ".join(fields)
    (candidate / "基础性能测试" / "fio.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    config_path = tmp_path / "compare.json"
    config_path.write_text(
        json.dumps(
            {
                "baseline": {"path": str(baseline), "kernel_version": "6.6.0-72.3.0"},
                "candidates": [{"path": str(candidate), "kernel_version": "6.6.0-72.5.0"}],
                "threshold_pct": 5.0,
            }
        ),
        encoding="utf-8",
    )
    excel_path = tmp_path / "对比表格.xlsx"

    exit_code = main(["--config", str(config_path), "--excel", str(excel_path)])

    assert exit_code == 0
    assert excel_path.is_file()


def test_命令行_出错时把堆栈写进日志并返回非零(tmp_path):
    """报错要落到本地日志文件里，便于事后排查，而不是只在终端一闪而过。"""
    log_dir = tmp_path / "logs"
    missing_config = tmp_path / "不存在的配置.json"

    exit_code = main(
        [
            "--config",
            str(missing_config),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(log_dir),
        ]
    )

    assert exit_code != 0
    log_text = (log_dir / "perf-compare.log").read_text(encoding="utf-8")
    assert "不存在的配置.json" in log_text
    assert "Traceback" in log_text


def _写配置(tmp_path, baseline, candidate):
    config_path = tmp_path / "compare.json"
    config_path.write_text(
        json.dumps(
            {
                "baseline": {"path": str(baseline)},
                "candidates": [{"path": str(candidate)}],
                "threshold_pct": 5.0,
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_命令行_一个套都没读到时报错而不是静默产出空表(tmp_path, capsys):
    """最危险的失败方式是「退出码 0 + 空表」：路径填错时用户以为跑成功了。"""
    empty = tmp_path / "空目录"
    empty.mkdir()
    config_path = _写配置(tmp_path, empty, empty)

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    assert exit_code != 0
    assert "结果目录" in capsys.readouterr().err


def test_命令行_文件在但解析不出数据时单独报告(tmp_path, capsys):
    """文件存在、但内容不符合预期格式时，不能笼统说「未找到」——
    否则用户无法判断是文件没生成、名字不对，还是格式变了。"""
    result_dir = tmp_path / "结果"
    result_dir.mkdir()
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(result_dir / "fio.txt"))
    (result_dir / "mysql_tpcc.txt").write_text("格式不对的内容\n", encoding="utf-8")
    config_path = _写配置(tmp_path, result_dir, result_dir)

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "mysql_tpcc.txt" in output
    assert "没解析出数据" in output


def test_命令行_表头名称来自配置(tmp_path):
    """两侧名称支持在配置里指定（需求方 2026-10-12）。

    注意：断言用的名称**不能出现在测试函数名里** —— pytest 会用函数名创建 tmp_path，
    而 CLI 会把路径打印出来，否则子串断言会被目录名意外满足（假通过）。
    """
    for side in ("b", "c"):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(target / "fio.txt"))

    config_path = tmp_path / "compare.json"
    config_path.write_text(
        json.dumps(
            {
                "baseline": {"path": str(tmp_path / "b"), "name": "openEuler-24.03-64K"},
                "candidates": [
                    {"path": str(tmp_path / "c"), "name": "openEuler-24.03-SP1-64K"}
                ],
                "threshold_pct": 5.0,
            }
        ),
        encoding="utf-8",
    )
    excel_path = tmp_path / "对比表格.xlsx"

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(excel_path),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    assert exit_code == 0
    workbook = openpyxl.load_workbook(str(excel_path))
    assert [cell.value for cell in workbook["汇总"][1]][:3] == [
        "测试套",
        "openEuler-24.03-64K",
        "openEuler-24.03-SP1-64K",
    ]
    assert [cell.value for cell in workbook["fio"][1]][:3] == [
        "测试子项",
        "openEuler-24.03-64K",
        "openEuler-24.03-SP1-64K",
    ]


def test_命令行_无效结果给出告警(tmp_path, capsys):
    """带无效标记的结果文件要提示 —— 其汇总值是估计值、不可作为可报告结果
    （需求方 2026-10-16 确认要告警）。"""
    result_dir = tmp_path / "结果"
    result_dir.mkdir()
    shutil.copy(
        str(FIXTURE / "基础性能测试" / "cpu2017_int_single.txt"),
        str(result_dir / "cpu2017_int_single.txt"),
    )
    config_path = _写配置(tmp_path, result_dir, result_dir)

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    warned = [line for line in output.splitlines() if line.startswith("    ⚠")]
    assert warned, "实际输出为：\n" + output
    # 断言按内容匹配而不是取第一条：该用例两侧同目录，会先打印「同一个目录」告警。
    invalid_lines = [line for line in warned if "INVALID RUN" in line]
    assert invalid_lines, "实际输出为：\n" + output
    assert "speccpu2017_int_single" in invalid_lines[0]


def test_命令行_两侧指向同一个目录时告警(tmp_path, capsys):
    """把同一份数据同时当基线和对比，结果必然全为 0 —— 必须明确告警。

    否则用户看到一张全 0 的表，会误以为「没有任何劣化」，这是假结论。
    """
    result_dir = tmp_path / "结果"
    result_dir.mkdir()
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(result_dir / "fio.txt"))
    config_path = _写配置(tmp_path, result_dir, result_dir)

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    warnings = [line for line in output.splitlines() if line.startswith("    ⚠")]
    assert any("同一个目录" in line for line in warnings), "实际输出为：\n" + output


def test_命令行_两侧数据完全一致时告警(tmp_path, capsys):
    """两个不同目录、内容却一模一样的拷贝 —— 同样应当告警。"""
    for side in ("base", "copy"):
        target = tmp_path / side / "基础性能测试"
        target.mkdir(parents=True)
        shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(target / "fio.txt"))
    config_path = _写配置(tmp_path, tmp_path / "base", tmp_path / "copy")

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    warnings = [line for line in output.splitlines() if line.startswith("    ⚠")]
    assert any("完全一致" in line for line in warnings), "实际输出为：\n" + output


def test_命令行_报告被排除的测试套(tmp_path, capsys):
    """只在一侧存在的套要明说被排除了，不能静默不出现。

    注意：断言必须**按行**匹配。pytest 会用函数名创建 tmp_path 目录，
    而 CLI 会把路径打印出来 —— 直接断言子串会被临时目录名意外满足（假通过）。
    """
    baseline = tmp_path / "baseline" / "基础性能测试"
    candidate = tmp_path / "candidate" / "基础性能测试"
    baseline.mkdir(parents=True)
    candidate.mkdir(parents=True)
    for name in ("fio.txt", "stream.txt"):
        shutil.copy(str(FIXTURE / "基础性能测试" / name), str(baseline / name))
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(candidate / "fio.txt"))
    config_path = _写配置(tmp_path, tmp_path / "baseline", tmp_path / "candidate")

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    skipped = [line for line in output.splitlines() if line.startswith("只在一侧出现")]
    assert skipped, "实际输出为：\n" + output
    assert "stream" in skipped[0]


def test_命令行_报告读到的套与未找到的套(tmp_path, capsys):
    """数据不全时要写清「读到哪些套、没找到哪些套」，便于定位是哪一侧缺数据。"""
    baseline = tmp_path / "baseline" / "基础性能测试"
    candidate = tmp_path / "candidate" / "基础性能测试"
    baseline.mkdir(parents=True)
    candidate.mkdir(parents=True)
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(baseline / "fio.txt"))
    shutil.copy(str(FIXTURE / "基础性能测试" / "fio.txt"), str(candidate / "fio.txt"))
    config_path = _写配置(tmp_path, tmp_path / "baseline", tmp_path / "candidate")

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--excel",
            str(tmp_path / "对比表格.xlsx"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "fio" in output
    assert "未找到" in output
