"""config 模块的行为规格。

测试只穿过约定的 seam：`perf_compare.config.load_config`。
"""
import json

from perf_compare.config import load_config


def test_加载配置_读出基线与各对比的结果目录(tmp_path):
    cfg_file = tmp_path / "compare.json"
    cfg_file.write_text(
        json.dumps(
            {
                "baseline": {"path": "/r/base", "kernel_version": "6.6.0-72.3.0"},
                "candidates": [
                    {"path": "/r/cand-a", "kernel_version": "6.6.0-72.5.0"},
                    {"path": "/r/cand-b", "kernel_version": "6.6.0-72.6.0"},
                ],
                "threshold_pct": 5.0,
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_file))

    assert cfg.baseline.path == "/r/base"
    assert cfg.baseline.kernel_version == "6.6.0-72.3.0"
    assert [c.path for c in cfg.candidates] == ["/r/cand-a", "/r/cand-b"]
    assert [c.kernel_version for c in cfg.candidates] == ["6.6.0-72.5.0", "6.6.0-72.6.0"]
    assert cfg.threshold_pct == 5.0
