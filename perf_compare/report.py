"""测试报告输出（txt + html）。

**硬性约束：报告里不得出现任何具体测量值**（这份报告对外公开）。
因此本模块只使用「劣化项名称 / 子项 / 劣化程度 / 系统标识」，绝不读写 `Row.baseline`、
`Row.candidate` 的数值 —— 唯一例外是 `pct`（差距百分比本身是分析结论，不是原始测量值），
且仅在 `style=3` 时以百分比形式出现。

三个版本（`style`）的区别只在「劣化程度怎么表达」：
- 1 定性   ：严重 / 明显 / 轻微
- 2 分档   ：5%~10% / 10%~30% / >30%
- 3 精确   ：带符号的百分比
"""
import datetime
import html
import os
import unicodedata

TXT_SUFFIX = ".txt"
HTML_SUFFIX = ".html"

STYLE_NAMES = {1: "定性分级", 2: "区间分档", 3: "精确百分比"}

# 劣化程度分档（上下界按「往变差方向的幅度」百分比）。
_GRADES = (
    (50.0, "严重", ">30%"),
    (20.0, "明显", "10%~30%"),
    (0.0, "轻微", "5%~10%"),
)


def write_report(comparison, base_path, labels=("结果A", "结果B"), info=None, style=3):
    """写出 `<base_path>.txt` 与 `<base_path>.html`，返回 (txt 路径, html 路径)。

    `info` 可含：`threshold_pct`、`baseline_kernel`、`candidate_kernel`、
    `baseline_commit`、`candidate_commit`、`generated_at`。
    """
    if style not in STYLE_NAMES:
        raise ValueError("未知的报告版本：{0!r}（可选 1/2/3）".format(style))
    labels = tuple(labels)
    info = dict(info or {})
    info.setdefault("compared_suites", len({row.suite for row in comparison.rows()}))
    findings = _findings(comparison, info.get("threshold_pct"), style)

    txt = _render_txt(findings, labels, info, style)
    page = _render_html(findings, labels, info, style)

    txt_path = base_path + TXT_SUFFIX
    html_path = base_path + HTML_SUFFIX
    _确保父目录存在(txt_path)
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(txt)
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(page)
    return txt_path, html_path


def _findings(comparison, threshold_pct, style):
    """把劣化子项整理成报告用的条目（**不含任何测量值**）。"""
    found = []
    for row in comparison.rows():
        if not row.degraded:
            continue
        magnitude = _magnitude(row)
        found.append(
            {
                "suite": row.suite,
                "name": row.item if not row.sub_item else "{0} / {1}".format(row.item, row.sub_item),
                "direction": "时延增大" if not row.higher_is_better else "指标下降",
                "grade": _grade(magnitude)[0],
                "amount": _amount(magnitude, style),
            }
        )
    found.sort(key=lambda item: (not item["grade"] == "严重", item["grade"], item["suite"]))
    return found


def _magnitude(row):
    """劣化的幅度（往变差方向的百分比）。"""
    if row.pct is None:
        return 0.0
    return -row.pct if row.higher_is_better else row.pct


def _grade(magnitude):
    for limit, name, band in _GRADES:
        if magnitude >= limit:
            return name, band
    return _GRADES[-1][0], _GRADES[-1][1]


def _amount(magnitude, style):
    """按版本给出「劣化程度」的表述 —— 只有它能携带量化信息。"""
    if style == 1:
        return ""
    if style == 2:
        return _grade(magnitude)[1]
    return "{0:.2f}%".format(magnitude)


def _render_txt(findings, labels, info, style):
    threshold = info.get("threshold_pct")
    stamp = info.get("generated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    suites = sorted({item["suite"] for item in findings})
    counts = _counts_by_grade(findings)

    lines = [
        "性能测试结果对比报告",
        "=" * 24,
        "",
        "对比对象：{0}（基线） vs {1}（对比）".format(labels[0], labels[1]),
        "内核版本：{0} / {1}".format(_标(info.get("baseline_kernel")), _标(info.get("candidate_kernel"))),
        "CommitId：{0} / {1}".format(_标(info.get("baseline_commit")), _标(info.get("candidate_commit"))),
        "劣化阈值：{0}".format(_标(threshold, "{}%")),
        "报告版本：{0}（{1}）".format(style, STYLE_NAMES[style]),
        "生成时间：{0}".format(stamp),
        "",
        "一、总体结论",
        "",
        _结论(findings, suites, counts, style),
        "",
        "二、劣化项清单",
        "",
    ]
    if not findings:
        lines.append("   本次未发现超过阈值的劣化项。")
    else:
        lines.append(
            "   {0}{1}{2}{3}".format(
                _补齐("序号", 6), _补齐("测试套 / 测试项", 46), _补齐("方向", 12), "劣化程度"
            )
        )
        lines.append("   " + "-" * 76)
        for index, item in enumerate(findings, 1):
            amount = item["amount"]
            lines.append(
                "   {0}{1}{2}{3}".format(
                    _补齐(str(index), 6),
                    _补齐(_截断("{0} / {1}".format(item["suite"], item["name"]), 44), 46),
                    _补齐(item["direction"], 12),
                    item["grade"] + ("（{0}）".format(amount) if amount else ""),
                )
            )
    lines.extend(
        [
            "",
            "三、说明",
            "",
            "   1. 本报告**不含任何具体测量值**，仅给出对比结论与劣化程度，可直接对外使用。",
            "   2. 劣化程度按「往变差方向的幅度」分级：严重 ≥50%，明显 ≥20%，轻微 >阈值。",
            "   3. 判定只针对两侧都包含的测试套；某项的劣化可能在套级被平均摊薄，",
            "      因此本报告以子项级结论为准。",
            "   4. 汇总口径逐套不同（部分取测试工具自带的汇总值），详见项目文档。",
            "",
            "四、分析提示词（可直接交给大模型继续分析）",
            "",
            "   你是一名性能工程专家。以下是某次性能测试的对比结论（数据已脱敏，不含测量值）：",
            "   - 对比对象：{0}（基线） vs {1}（对比）".format(labels[0], labels[1]),
            "   - 劣化阈值：{0}".format(_标(threshold, "{}%")),
            "   - 判定结果：共比对 {0} 个测试套，其中 {1} 个套出现劣化，合计 {2} 项。".format(
                info.get("compared_suites"), len(suites), len(findings)
            ),
            "   - 劣化项（套 / 项 / 方向 / 程度）：",
        ]
    )
    for item in findings:
        lines.append(
            "     · {0} / {1} —— {2}，{3}".format(item["suite"], item["name"], item["direction"], item["grade"])
        )
    lines.extend(
        [
            "   请据此输出：① 本次劣化的整体特征；② 各劣化项之间可能的共性原因；",
            "   ③ 按影响面与严重程度排序的排查优先级；④ 建议的验证与回归方式。",
            "   注意：不要编造任何具体测量数值。",
            "",
        ]
    )
    return "\n".join(lines)


def _结论(findings, suites, counts, style):
    if not findings:
        return "   本次对比未发现超过阈值的劣化项，测试结果整体稳定。"
    detail = "、".join("{0} {1} 项".format(name, number) for name, number in counts if number)
    return (
        "   本次共发现 {0} 项超过阈值的劣化，涉及 {1} 个测试套（{2}）。\n"
        "   按严重程度：{3}。建议优先关注「严重」类问题。".format(
            len(findings), len(suites), "、".join(suites), detail
        )
    )


def _counts_by_grade(findings):
    order = ["严重", "明显", "轻微"]
    return [(name, sum(1 for item in findings if item["grade"] == name)) for name in order]


def _render_html(findings, labels, info, style):
    threshold = info.get("threshold_pct")
    stamp = info.get("generated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    suites = sorted({item["suite"] for item in findings})
    counts = _counts_by_grade(findings)
    by_suite = _counts_by_suite(findings)

    rows_html = "\n".join(
        [
            "<tr><td>{0}</td><td>{1}</td><td>{2}</td><td>"
            "<span class='badge g-{3}'>{4}</span>{5}</td></tr>".format(
                index,
                html.escape("{0} / {1}".format(item["suite"], item["name"])),
                html.escape(item["direction"]),
                _grade_slug(item["grade"]),
                html.escape(item["grade"]),
                " <span class='amount'>{0}</span>".format(html.escape(item["amount"]))
                if item["amount"]
                else "",
            )
            for index, item in enumerate(findings, 1)
        ]
    ) or "<tr><td colspan='4' class='empty'>本次未发现超过阈值的劣化项</td></tr>"

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>性能测试结果对比报告</title>
<style>
  :root {{ --ink:#1f2733; --muted:#6b7684; --line:#e3e8ef; --severe:#c0392b; --obvious:#e67e22; --slight:#c9a227; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:32px 20px 60px; background:#f6f8fb; color:var(--ink);
         font:15px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  header {{ background:linear-gradient(135deg,#1f4e79,#2e75b6); color:#fff; border-radius:14px;
            padding:26px 30px; box-shadow:0 8px 24px rgba(31,78,121,.18); }}
  header h1 {{ margin:0 0 6px; font-size:24px; letter-spacing:.5px; }}
  header .sub {{ opacity:.9; font-size:14px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin:20px 0; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px 18px; }}
  .card .k {{ color:var(--muted); font-size:13px; }}
  .card .v {{ font-size:26px; font-weight:700; margin-top:4px; }}
  section {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:22px 24px; margin-bottom:18px; }}
  h2 {{ font-size:17px; margin:0 0 14px; padding-left:10px; border-left:4px solid #2e75b6; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th,td {{ text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--muted); font-weight:600; background:#fbfcfe; }}
  tr:hover td {{ background:#fbfcfe; }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:12.5px; color:#fff; }}
  .g-severe {{ background:var(--severe); }}
  .g-obvious {{ background:var(--obvious); }}
  .g-slight {{ background:var(--slight); }}
  .amount {{ color:var(--muted); font-size:12.5px; }}
  .empty {{ color:var(--muted); text-align:center; padding:22px; }}
  .chart {{ margin:6px 0 2px; }}
  .legend {{ display:flex; gap:18px; flex-wrap:wrap; color:var(--muted); font-size:13px; margin-top:8px; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }}
  .meta {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px 24px;
           font-size:14px; }}
  .meta div {{ display:flex; gap:8px; }}
  .meta .k {{ color:var(--muted); min-width:76px; }}
  details {{ margin-top:6px; }}
  summary {{ cursor:pointer; color:#2e75b6; font-size:14px; }}
  pre {{ background:#f7f9fc; border:1px solid var(--line); border-radius:10px; padding:14px;
         white-space:pre-wrap; word-break:break-word; font-size:13px; }}
  footer {{ color:var(--muted); font-size:12.5px; text-align:center; margin-top:26px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>性能测试结果对比报告</h1>
    <div class="sub">{label_a}（基线） &nbsp;vs&nbsp; {label_b}（对比） &nbsp;·&nbsp; 阈值 {threshold}</div>
  </header>

  <div class="cards">
    <div class="card"><div class="k">劣化项</div><div class="v">{total}</div></div>
    <div class="card"><div class="k">涉及测试套</div><div class="v">{suite_count}</div></div>
    <div class="card"><div class="k">严重</div><div class="v" style="color:var(--severe)">{severe}</div></div>
    <div class="card"><div class="k">明显</div><div class="v" style="color:var(--obvious)">{obvious}</div></div>
    <div class="card"><div class="k">轻微</div><div class="v" style="color:var(--slight)">{slight}</div></div>
  </div>

  <section>
    <h2>劣化程度分布</h2>
    <div class="chart">{chart_grade}</div>
    <div class="legend">
      <span><i class="dot" style="background:var(--severe)"></i>严重（≥50%）</span>
      <span><i class="dot" style="background:var(--obvious)"></i>明显（≥20%）</span>
      <span><i class="dot" style="background:var(--slight)"></i>轻微（超阈值）</span>
    </div>
  </section>

  <section>
    <h2>各测试套劣化项数</h2>
    <div class="chart">{chart_suite}</div>
  </section>

  <section>
    <h2>劣化项清单</h2>
    <table>
      <thead><tr><th style="width:56px">序号</th><th>测试套 / 测试项</th><th style="width:110px">方向</th>
      <th style="width:190px">劣化程度</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </section>

  <section>
    <h2>系统标识</h2>
    <div class="meta">
      <div><span class="k">内核版本</span><span>{kernel_a} / {kernel_b}</span></div>
      <div><span class="k">CommitId</span><span>{commit_a} / {commit_b}</span></div>
      <div><span class="k">劣化阈值</span><span>{threshold}</span></div>
      <div><span class="k">报告版本</span><span>V{style} · {style_name}</span></div>
      <div><span class="k">生成时间</span><span>{stamp}</span></div>
    </div>
  </section>

  <section>
    <h2>说明</h2>
    <p>本报告<strong>不含任何具体测量值</strong>，仅给出对比结论与劣化程度，可直接对外使用。</p>
    <p>劣化程度按「往变差方向的幅度」分级：严重 ≥50%，明显 ≥20%，轻微 &gt; 阈值。判定只针对两侧都包含的测试套；
    某项的劣化可能在套级被平均摊薄，因此以子项级结论为准。</p>
    <details>
      <summary>分析提示词（可直接交给大模型继续分析）</summary>
      <pre>{prompt}</pre>
    </details>
  </section>

  <footer>本页由 perf-compare 生成 · 数据已脱敏</footer>
</div>
</body>
</html>
""".format(
        style=style,
        style_name=STYLE_NAMES[style],
        label_a=html.escape(labels[0]),
        label_b=html.escape(labels[1]),
        threshold=html.escape(_标(threshold, "{}%")),
        total=len(findings),
        suite_count=len(suites),
        severe=counts[0][1],
        obvious=counts[1][1],
        slight=counts[2][1],
        chart_grade=_svg_bars([(name, number, _GRADE_COLORS[name]) for name, number in counts]),
        chart_suite=_svg_bars(
            [(name, number, "#2e75b6") for name, number in by_suite], label_width=150
        ),
        rows=rows_html,
        kernel_a=html.escape(_标(info.get("baseline_kernel"))),
        kernel_b=html.escape(_标(info.get("candidate_kernel"))),
        commit_a=html.escape(_标(info.get("baseline_commit"))),
        commit_b=html.escape(_标(info.get("candidate_commit"))),
        stamp=html.escape(stamp),
        prompt=html.escape(_prompt(findings, labels, threshold, style)),
    )


_GRADE_COLORS = {"严重": "#c0392b", "明显": "#e67e22", "轻微": "#c9a227"}


def _counts_by_suite(findings):
    order = []
    for item in findings:
        if item["suite"] not in order:
            order.append(item["suite"])
    return [(suite, sum(1 for item in findings if item["suite"] == suite)) for suite in order]


def _grade_slug(grade):
    return {"严重": "severe", "明显": "obvious"}.get(grade, "slight")


def _svg_bars(items, label_width=64):
    """把计数画成横向条形图（内联 SVG，不依赖任何外部资源）。"""
    if not items or not any(number for _, number, _ in items):
        return "<svg width='100%' height='34'><text x='4' y='22' fill='#6b7684'>无劣化项</text></svg>"
    maximum = max(number for _, number, _ in items) or 1
    bar_height, gap = 22, 10
    width = 640
    height = len(items) * (bar_height + gap) + 6
    parts = ["<svg viewBox='0 0 {0} {1}' width='100%' height='{1}' role='img'>".format(width, height)]
    for index, (label, number, color) in enumerate(items):
        y = index * (bar_height + gap) + 3
        usable = width - label_width - 52
        # 计数为 0 时不画条（画一小截会被误读成「有一点点」）
        length = 0 if not number else max(int(usable * number / maximum), 3)
        parts.append(
            "<text x='0' y='{0}' fill='#1f2733' font-size='13'>{1}</text>".format(
                y + 16, html.escape(str(label))
            )
        )
        if length:
            parts.append(
                "<rect x='{0}' y='{1}' width='{2}' height='{3}' rx='4' fill='{4}'/>".format(
                    label_width, y, length, bar_height, color
                )
            )
        parts.append(
            "<text x='{0}' y='{1}' fill='#6b7684' font-size='12.5'>{2}</text>".format(
                label_width + length + 8, y + 16, number
            )
        )
    parts.append("</svg>")
    return "".join(parts)


def _prompt(findings, labels, threshold, style):
    lines = [
        "你是一名性能工程专家。以下是某次性能测试的对比结论（数据已脱敏，不含任何测量值）：",
        "对比对象：{0}（基线） vs {1}（对比）".format(labels[0], labels[1]),
        "劣化阈值：{0}".format(_标(threshold, "{}%")),
        "劣化项（套 / 项 / 方向 / 程度）：",
    ]
    for item in findings:
        lines.append("  · {0} / {1} —— {2}，{3}".format(item["suite"], item["name"], item["direction"], item["grade"]))
    lines.extend(
        [
            "请据此输出：① 本次劣化的整体特征；② 各劣化项之间可能的共性原因；",
            "③ 按影响面与严重程度排序的排查优先级；④ 建议的验证与回归方式。",
            "注意：不要编造任何具体测量数值。",
        ]
    )
    return "\n".join(lines)


def _标(value, template=None):
    """报告里的空值统一写 `未提供`，不留空白。"""
    if value is None or value == "":
        return "未提供"
    if template is not None and "{" in template:
        return template.format(value)
    return str(value)


def _宽度(text):
    """显示宽度：中日韩全角字符占两格，用于 TXT 表格对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _补齐(text, width):
    """按**显示宽度**左对齐补齐，避免中文列错位。"""
    return text + " " * max(width - _宽度(text), 0)


def _截断(text, limit):
    """按显示宽度截断，超长补省略号。"""
    if _宽度(text) <= limit:
        return text
    out, used = [], 0
    for ch in text:
        step = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + step > limit - 1:
            break
        out.append(ch)
        used += step
    return "".join(out) + "…"


def _确保父目录存在(path):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
