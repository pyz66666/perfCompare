"""测试报告输出（txt + html）。

**硬性约束：报告里不得出现任何具体测量值**（这份报告对外公开）。
本模块只使用「劣化项名称 / 子项 / 方向 / 劣化程度」，绝不读写 `Row.baseline`、`Row.candidate`
的数值 —— 唯一例外是 `pct`（差距百分比本身是分析结论，不是原始测量值）。

`summarize_subitems`（默认关闭）决定报告的**粒度**：
- 关闭：劣化清单只到「测试套」一级（等同汇总表那一栏），不出现测试项、子项名，
        也不显示「各测试套劣化项数」图表；
- 开启：清单到「测试项」一级，并额外输出「子项劣化汇总」一节与按套的图表。

劣化程度统一用**精确百分比**表达（如 25.00%）。
系统标识里**暂不显示报告版本与 commitId**（需求方 2026-10-19）。
"""
import datetime
import html
import os
import unicodedata

TXT_SUFFIX = ".txt"
HTML_SUFFIX = ".html"

# 劣化程度分档：(阈值, 名称, 区间文案)
_GRADES = (
    (50.0, "严重"),
    (20.0, "明显"),
    (0.0, "轻微"),
)
_GRADE_COLORS = {"严重": "#c0392b", "明显": "#e67e22", "轻微": "#c9a227"}

# 报告粒度（由 summarize_subitems 决定）
_SUITE, _ITEM, _SUB = "suite", "item", "sub"
_水平头 = {
    _SUITE: "测试套",
    _ITEM: "测试套 / 测试项",
    _SUB: "测试套 / 测试项 / 子项",
}


def write_report(
    comparison,
    base_path,
    labels=("结果A", "结果B"),
    info=None,
    summarize_subitems=False,
):
    """写出 `<base_path>.txt` 与 `<base_path>.html`，返回 (txt 路径, html 路径)。"""
    labels = tuple(labels)
    info = dict(info or {})
    info.setdefault("compared_suites", len({row.suite for row in comparison.rows()}))

    if summarize_subitems:
        level = _ITEM
        entries = _item_findings(comparison)
        subs = _subitem_findings(comparison)
    else:
        level = _SUITE
        entries = _suite_findings(comparison)
        subs = []

    txt_path = base_path + TXT_SUFFIX
    html_path = base_path + HTML_SUFFIX
    _确保父目录存在(txt_path)
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(_render_txt(entries, subs, labels, info, level))
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(_render_html(entries, subs, labels, info, level))
    return txt_path, html_path


# ——— 结论条目 ———


def _entry(row):
    # 分级与显示必须用**同一个**四舍五入后的幅度：否则 19.999999999999996 会显示成
    # 20.00% 却被判「轻微」（20% 本应属「明显」），结论与显示自相矛盾。
    magnitude = round(_magnitude(row), 2)
    grade = _grade(magnitude)
    return {
        "suite": row.suite,
        "item": row.item,
        "sub_item": row.sub_item,
        "direction": "时延增大" if not row.higher_is_better else "指标下降",
        "grade": grade,
        "amount": _amount(magnitude),
        "magnitude": magnitude,
    }


def _suite_findings(comparison):
    """按测试套聚合（开关关闭时的粒度，等同汇总表那一栏）。"""
    worst = {}
    for row in comparison.rows():
        if not row.degraded:
            continue
        entry = _entry(row)
        if entry["suite"] not in worst or entry["magnitude"] > worst[entry["suite"]]["magnitude"]:
            worst[entry["suite"]] = entry
    return _sorted(worst.values())


def _item_findings(comparison):
    """按「测试套 + 测试项」聚合。"""
    worst = {}
    for row in comparison.rows():
        if not row.degraded:
            continue
        entry = _entry(row)
        key = (entry["suite"], entry["item"])
        if key not in worst or entry["magnitude"] > worst[key]["magnitude"]:
            worst[key] = entry
    return _sorted(worst.values())


def _subitem_findings(comparison):
    found = {}
    for row in comparison.rows():
        if not row.degraded:
            continue
        entry = _entry(row)
        found[(entry["suite"], entry["item"], entry["sub_item"])] = entry
    return _sorted(found.values())


def _sorted(entries):
    return sorted(
        entries, key=lambda entry: (-entry["magnitude"], entry["suite"], entry["item"])
    )


def _magnitude(row):
    """劣化的幅度（往变差方向的百分比）。"""
    if row.pct is None:
        return 0.0
    return -row.pct if row.higher_is_better else row.pct


def _grade(magnitude):
    for limit, name in _GRADES:
        if magnitude >= limit:
            return name
    return _GRADES[-1][1]


def _amount(magnitude):
    """劣化程度的量化表述：统一给精确百分比。"""
    return "{0:.2f}%".format(magnitude)


def _label(entry, level):
    if level == _SUITE:
        return entry["suite"]
    if level == _SUB and entry["sub_item"]:
        return "{0} / {1} / {2}".format(entry["suite"], entry["item"], entry["sub_item"])
    return "{0} / {1}".format(entry["suite"], entry["item"])


def _degree(entry):
    return entry["grade"] + ("（{0}）".format(entry["amount"]) if entry["amount"] else "")


def _清单标题(level):
    return "二、劣化测试套清单" if level == _SUITE else "二、劣化项清单"


def _指标名(level):
    return "劣化测试套" if level == _SUITE else "劣化测试项"


# ——— TXT ———


def _render_txt(entries, subs, labels, info, level):
    stamp = info.get("generated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    suites = sorted({entry["suite"] for entry in entries})

    lines = [
        "性能测试结果对比报告",
        "=" * 24,
        "",
        "对比对象：{0}（基线） vs {1}（对比）".format(labels[0], labels[1]),
        "内核版本：{0} / {1}".format(
            _标(info.get("baseline_kernel")), _标(info.get("candidate_kernel"))
        ),
        "劣化阈值：{0}".format(_标(info.get("threshold_pct"), "{}%")),
        "生成时间：{0}".format(stamp),
        "",
        "一、总体结论",
        "",
        _结论(entries, suites, level),
        "",
        _清单标题(level),
        "",
    ]
    lines += _txt_table(entries, level) if entries else ["   本次未发现超过阈值的劣化项。"]

    section = 3
    if subs:
        lines += ["", "{0}、子项劣化汇总".format(_序号(section)), ""]
        lines += _txt_table(subs, _SUB)
        section += 1

    lines += [
        "",
        "{0}、说明".format(_序号(section)),
        "",
        "   1. 本报告**不含任何具体测量值**，仅给出对比结论与劣化程度，可直接对外使用。",
        "   2. 劣化程度按「往变差方向的幅度」分级：严重 ≥50%，明显 ≥20%，轻微 > 阈值。",
        "   3. 判定只针对两侧都包含的测试套；某项的劣化可能在套级被平均摊薄，",
        "      因此本报告以子项级结论为准。",
        "   4. 汇总口径逐套不同（部分取测试工具自带的汇总值），详见项目文档。",
    ]
    section += 1

    lines += ["", "{0}、分析提示词（可直接交给大模型继续分析）".format(_序号(section)), ""]
    lines += _prompt_lines(entries, subs, labels, info, level)
    lines.append("")
    return "\n".join(lines)


def _txt_table(entries, level):
    rows = [
        "   {0}{1}{2}劣化程度".format(
            _补齐("序号", 6), _补齐(_水平头[level], 46), _补齐("方向", 12)
        ),
        "   " + "-" * 76,
    ]
    for index, entry in enumerate(entries, 1):
        rows.append(
            "   {0}{1}{2}{3}".format(
                _补齐(str(index), 6),
                _补齐(_截断(_label(entry, level), 44), 46),
                _补齐(entry["direction"], 12),
                _degree(entry),
            )
        )
    return rows


def _prompt_lines(entries, subs, labels, info, level):
    lines = [
        "   你是一名性能工程专家。以下是某次性能测试的对比结论（数据已脱敏，不含测量值）：",
        "   - 对比对象：{0}（基线） vs {1}（对比）".format(labels[0], labels[1]),
        "   - 劣化阈值：{0}".format(_标(info.get("threshold_pct"), "{}%")),
        "   - 判定结果：共比对 {0} 个测试套，其中 {1} 个套出现劣化，合计 {2} 个{3}。".format(
            info.get("compared_suites"),
            len({entry["suite"] for entry in entries}),
            len(entries),
            "分析单位" if level == _SUITE else "测试项",
        ),
        "   - 劣化项（{0} / 方向 / 程度）：".format(_水平头[level]),
    ]
    for entry in entries:
        lines.append(
            "     · {0} —— {1}，{2}".format(_label(entry, level), entry["direction"], entry["grade"])
        )
    if subs:
        lines.append("   - 劣化子项（套 / 项 / 子项 / 方向 / 程度）：")
        for entry in subs:
            lines.append(
                "     · {0} —— {1}，{2}".format(_label(entry, _SUB), entry["direction"], entry["grade"])
            )
    lines += [
        "   请据此输出：① 本次劣化的整体特征；② 各劣化项之间可能的共性原因；",
        "   ③ 按影响面与严重程度排序的排查优先级；④ 建议的验证与回归方式。",
        "   注意：不要编造任何具体测量数值。",
    ]
    return lines


def _结论(entries, suites, level):
    if not entries:
        return "   本次对比未发现超过阈值的劣化项，测试结果整体稳定。"
    counts = "、".join(
        "{0} {1} 项".format(name, sum(1 for entry in entries if entry["grade"] == name))
        for _, name in _GRADES
    )
    if level == _SUITE:
        return (
            "   本次共发现 {0} 个测试套存在超过阈值的劣化（{1}）。\n"
            "   按严重程度：{2}。建议优先关注「严重」类问题。".format(
                len(entries), "、".join(suites), counts
            )
        )
    return (
        "   本次共发现 {0} 个测试项超过阈值的劣化，涉及 {1} 个测试套（{2}）。\n"
        "   按严重程度：{3}。建议优先关注「严重」类问题。".format(
            len(entries), len(suites), "、".join(suites), counts
        )
    )


def _序号(number):
    return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}.get(number, str(number))


# ——— HTML ———


def _render_html(entries, subs, labels, info, level):
    stamp = info.get("generated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    suites = sorted({entry["suite"] for entry in entries})
    counts = [
        (name, sum(1 for entry in entries if entry["grade"] == name)) for _, name in _GRADES
    ]

    # 「各测试套劣化项数」只在展开到测试项/子项时才有意义（套级清单本身就是按套列的）
    chart_by_suite = ""
    if level != _SUITE:
        chart_by_suite = """
  <section>
    <h2>各测试套劣化项数</h2>
    <div class="chart">{chart}</div>
  </section>
""".format(
            chart=_svg_bars(
                [(name, number, "#2e75b6") for name, number in _counts_by_suite(entries)],
                label_width=150,
            )
        )

    subs_section = ""
    if subs:
        subs_section = """
  <section>
    <h2>子项劣化汇总</h2>
    <table>
      <thead><tr><th style="width:56px">序号</th><th>测试套 / 测试项 / 子项</th>
      <th style="width:110px">方向</th><th style="width:190px">劣化程度</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </section>
""".format(rows=_table_rows(subs, _SUB))

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
  .meta {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px 24px; font-size:14px; }}
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
    <div class="card"><div class="k">{metric}</div><div class="v">{total}</div></div>
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
{chart_by_suite}
  <section>
    <h2>{list_title}</h2>
    <table>
      <thead><tr><th style="width:56px">序号</th><th>{head}</th><th style="width:110px">方向</th>
      <th style="width:190px">劣化程度</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </section>
{subs_section}
  <section>
    <h2>系统标识</h2>
    <div class="meta">
      <div><span class="k">内核版本</span><span>{kernel_a} / {kernel_b}</span></div>
      <div><span class="k">劣化阈值</span><span>{threshold}</span></div>
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
        label_a=html.escape(labels[0]),
        label_b=html.escape(labels[1]),
        threshold=html.escape(_标(info.get("threshold_pct"), "{}%")),
        metric=_指标名(level),
        total=len(entries),
        suite_count=len(suites),
        severe=counts[0][1],
        obvious=counts[1][1],
        slight=counts[2][1],
        chart_grade=_svg_bars([(name, number, _GRADE_COLORS[name]) for name, number in counts]),
        chart_by_suite=chart_by_suite,
        list_title=_清单标题(level).split("、", 1)[1],
        head=_水平头[level],
        rows=_table_rows(entries, level),
        subs_section=subs_section,
        kernel_a=html.escape(_标(info.get("baseline_kernel"))),
        kernel_b=html.escape(_标(info.get("candidate_kernel"))),
        stamp=html.escape(stamp),
        prompt=html.escape("\n".join(_prompt_lines(entries, subs, labels, info, level))),
    )


def _table_rows(entries, level):
    if not entries:
        return "<tr><td colspan='4' class='empty'>本次未发现超过阈值的劣化项</td></tr>"
    rows = []
    for index, entry in enumerate(entries, 1):
        rows.append(
            "<tr><td>{0}</td><td>{1}</td><td>{2}</td><td>"
            "<span class='badge g-{3}'>{4}</span>{5}</td></tr>".format(
                index,
                html.escape(_label(entry, level)),
                html.escape(entry["direction"]),
                _grade_slug(entry["grade"]),
                html.escape(entry["grade"]),
                " <span class='amount'>{0}</span>".format(html.escape(entry["amount"]))
                if entry["amount"]
                else "",
            )
        )
    return "\n".join(rows)


def _counts_by_suite(entries):
    order = []
    for entry in entries:
        if entry["suite"] not in order:
            order.append(entry["suite"])
    return [
        (suite, sum(1 for entry in entries if entry["suite"] == suite)) for suite in order
    ]


def _grade_slug(grade):
    return {"严重": "severe", "明显": "obvious"}.get(grade, "slight")


def _svg_bars(items, label_width=64):
    """把计数画成横向条形图（内联 SVG，不依赖任何外部资源）。"""
    if not items or not any(number for _, number, _ in items):
        return (
            "<svg width='100%' height='34'>"
            "<text x='4' y='22' fill='#6b7684'>无劣化项</text></svg>"
        )
    maximum = max(number for _, number, _ in items) or 1
    bar_height, gap, width = 22, 10, 640
    height = len(items) * (bar_height + gap) + 6
    parts = [
        "<svg viewBox='0 0 {0} {1}' width='100%' height='{1}' role='img'>".format(width, height)
    ]
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


# ——— 小工具 ———


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
    return text + " " * max(width - _宽度(text), 0)


def _截断(text, limit):
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


# ——— 多候选（多版本）报告 ———
#
# 语义：每个候选都与**同一个基线**各比一次（不是相邻版本链式对比）。
# 报告的独特价值在「跨候选矩阵」：同一个劣化项在哪些版本上出现，
# 据此区分「持续问题 / 某版本新引入 / 后续已恢复」。


def write_multi_report(
    comparisons,
    base_path,
    baseline_label,
    candidate_labels,
    info=None,
    summarize_subitems=False,
):
    """写多候选报告（一份 txt + 一份 html）。

    `comparisons` 与 `candidate_labels` 一一对应，顺序即配置里的候选顺序（当作时间序）。
    """
    labels = tuple(candidate_labels)
    if len(comparisons) != len(labels):
        raise ValueError("comparisons 与 candidate_labels 数量不一致")
    info = dict(info or {})
    level = _ITEM if summarize_subitems else _SUITE

    per_candidate = [
        (_item_findings(comparison) if summarize_subitems else _suite_findings(comparison))
        for comparison in comparisons
    ]

    txt_path = base_path + TXT_SUFFIX
    html_path = base_path + HTML_SUFFIX
    _确保父目录存在(txt_path)
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(
            _render_multi_txt(per_candidate, labels, baseline_label, info, level, comparisons)
        )
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(
            _render_multi_html(per_candidate, labels, baseline_label, info, level, comparisons)
        )
    return txt_path, html_path


def _matrix_keys(per_candidate, level):
    """所有候选出现过的劣化项（取并集），按最严重程度倒序。"""
    worst = {}
    for entries in per_candidate:
        for entry in entries:
            key = _key_of(entry, level)
            worst[key] = max(worst.get(key, 0.0), entry["magnitude"])
    return [key for key, _ in sorted(worst.items(), key=lambda pair: -pair[1])]


def _key_of(entry, level):
    if level == _SUITE:
        return (entry["suite"],)
    return (entry["suite"], entry["item"])


def _key_label(key, level):
    return key[0] if level == _SUITE else "{0} / {1}".format(key[0], key[1])


def _lookup(entries, level):
    return {_key_of(entry, level): entry for entry in entries}


def _归纳(degraded_labels, all_labels):
    """跨候选归纳：全部劣化=持续问题；部分=那些版本引入；后面恢复正常=已恢复。"""
    if not degraded_labels:
        return ""
    if len(degraded_labels) == len(all_labels):
        return "全部版本均劣化（持续问题）"
    text = "{0} 出现劣化".format("、".join(degraded_labels))
    last = all_labels[-1]
    if last not in degraded_labels and len(all_labels) > 1:
        text += "，后续已恢复"
    return text


def _render_multi_txt(per_candidate, labels, baseline_label, info, level, comparisons):
    stamp = info.get("generated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    threshold = info.get("threshold_pct")
    totals = [len(entries) for entries in per_candidate]
    keys = _matrix_keys(per_candidate, level)

    lines = [
        "性能测试结果对比报告（多版本）",
        "=" * 30,
        "",
        "对比对象：{0}（基线） vs {1}".format(baseline_label, "、".join(labels)),
        "内核版本：{0}".format(_标(info.get("baseline_kernel"))),
        "劣化阈值：{0}".format(_标(threshold, "{}%")),
        "生成时间：{0}".format(stamp),
        "",
        "一、跨版本概览",
        "",
        "   {0}{1}{2}".format(
            _补齐("候选版本", 30), _补齐("已比对套数", 14), "劣化项数"
        ),
        "   " + "-" * 56,
    ]
    for index, label in enumerate(labels):
        lines.append(
            "   {0}{1}{2}".format(
                _补齐(_截断(label, 28), 30),
                _补齐(str(_套数(comparisons[index])), 14),
                totals[index],
            )
        )

    lines += ["", "二、劣化矩阵", ""]
    if not keys:
        lines.append("   各候选均未发现超过阈值的劣化项。")
    else:
        # 候选名很长时直接截断会截出两列同名（`openEuler…`），必须先去掉公共前缀再截尾。
        shorts = _short_labels(labels, 12)
        header = "   {0}".format(_补齐(_水平头[level], 34))
        for short in shorts:
            header += _补齐(short, 12)
        lines.append(header + "结论")
        lines.append("   " + "-" * (34 + 12 * len(labels) + 20))
        lookups = [_lookup(entries, level) for entries in per_candidate]
        for key in keys:
            row = "   {0}".format(_补齐(_截断(_key_label(key, level), 32), 34))
            degraded_labels = []
            for index, label in enumerate(labels):
                entry = lookups[index].get(key)
                if entry is None:
                    row += _补齐("—", 12)
                else:
                    degraded_labels.append(label)
                    row += _补齐(entry["amount"] or entry["grade"], 12)
            short_of = dict(zip(labels, shorts))
            lines.append(
                row
                + _归纳([short_of[label] for label in degraded_labels], shorts)
            )
        if shorts != list(labels):
            lines.append("")
            lines.append(
                "   列名对应：{0}".format(
                    "；".join("{0} = {1}".format(a, b) for a, b in zip(shorts, labels))
                )
            )

    lines += ["", "三、按候选看明细", ""]
    for index, label in enumerate(labels):
        lines.append("   ▸ {0}（与基线 {1} 对比）".format(label, baseline_label))
        entries = per_candidate[index]
        if not entries:
            lines.append("     未发现超过阈值的劣化项。")
        else:
            for order, entry in enumerate(entries, 1):
                lines.append(
                    "     {0} {1} —— {2}，{3}".format(
                        order,
                        _label(entry, level),
                        entry["direction"],
                        _degree(entry),
                    )
                )
        lines.append("")

    lines += [
        "四、说明",
        "",
        "   1. 每个候选都与**同一个基线**各比一次（不是相邻版本链式对比）。",
        "   2. 本报告**不含任何具体测量值**，可直接对外使用。",
        "   3. 劣化程度按「往变差方向的幅度」分级：严重 ≥50%，明显 ≥20%，轻微 > 阈值。",
        "   4. 矩阵「结论」列的含义：全部版本都劣化 = 持续问题；只有部分版本劣化 = 那些版本引入；",
        "      先劣化后正常 = 已恢复。",
        "",
        "五、分析提示词（可直接交给大模型继续分析）",
        "",
        "   你是一名性能工程专家。以下是某次性能测试的**多版本**对比结论（数据已脱敏，不含测量值）：",
        "   - 基线：{0}；候选：{1}".format(baseline_label, "、".join(labels)),
        "   - 劣化阈值：{0}".format(_标(threshold, "{}%")),
        "   - 各候选劣化项数：{0}".format(
            "、".join("{0} {1} 项".format(label, total) for label, total in zip(labels, totals))
        ),
        "   - 劣化矩阵（项 / 各候选程度 / 归纳）：",
    ]
    lookups = [_lookup(entries, level) for entries in per_candidate]
    for key in keys:
        cells = []
        degraded_labels = []
        for index, label in enumerate(labels):
            entry = lookups[index].get(key)
            if entry is None:
                cells.append("—")
            else:
                degraded_labels.append(label)
                cells.append(entry["amount"] or entry["grade"])
        lines.append(
            "     · {0}：{1}（{2}）".format(
                _key_label(key, level), " / ".join(cells), _归纳(degraded_labels, labels)
            )
        )
    lines += [
        "   请据此输出：① 哪些是长期存在的持续问题、哪些是某个版本新引入的回归；",
        "   ② 各问题可能的共性原因；③ 按影响面与严重程度排序的排查优先级；④ 建议的验证方式。",
        "   注意：不要编造任何具体测量数值。",
        "",
    ]
    return "\n".join(lines)


def _short_labels(labels, width=12):
    """给候选名取「能互相区分」的短名：去掉公共前缀、截尾。

    直接用 _截断 从头截，长名字会截成一模一样的 `openEuler…`，两列无法区分。
    """
    labels = list(labels)
    # 公共前缀只能切到「最后一个分隔符」为止，否则会把 `SP1`/`SP2` 共有的 `SP` 也切掉，
    # 剩下 `1-64K`/`2-64K` —— 虽然可区分，但看不出是哪个版本。
    common = os.path.commonprefix(labels)
    boundary = max(common.rfind(sep) for sep in ("-", "_", "/", " "))
    common = common[: boundary + 1] if boundary > 0 else ""
    shorts = []
    for label in labels:
        text = label[len(common):].lstrip("-_ ") if common else label
        if not text:
            text = label
        if _宽度(text) > width:
            text = "…" + _尾部(text, width - 1)
        shorts.append(text)
    # 去重失败就退回全名，宁可宽也不能两列同名。
    return shorts if len(set(shorts)) == len(shorts) else labels


def _尾部(text, width):
    """从末尾取字符，直到显示宽度不超过 width。"""
    out, used = [], 0
    for char in reversed(text):
        step = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + step > width:
            break
        out.append(char)
        used += step
    return "".join(reversed(out))


def _套数(comparison):
    return len({row.suite for row in comparison.rows()})


def _render_multi_html(per_candidate, labels, baseline_label, info, level, comparisons):
    stamp = info.get("generated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    threshold = info.get("threshold_pct")
    totals = [len(entries) for entries in per_candidate]
    keys = _matrix_keys(per_candidate, level)
    lookups = [_lookup(entries, level) for entries in per_candidate]

    cards = "".join(
        '<div class="card"><div class="k">{0}</div><div class="v">{1}</div></div>'.format(
            html.escape(label), total
        )
        for label, total in zip(labels, totals)
    )

    matrix_rows = []
    for key in keys:
        cells = []
        degraded_labels = []
        for index, label in enumerate(labels):
            entry = lookups[index].get(key)
            if entry is None:
                cells.append("<td class='dash'>—</td>")
            else:
                degraded_labels.append(label)
                cells.append(
                    "<td><span class='badge g-{0}'>{1}</span>{2}</td>".format(
                        _grade_slug(entry["grade"]),
                        html.escape(entry["grade"]),
                        " <span class='amount'>{0}</span>".format(html.escape(entry["amount"]))
                        if entry["amount"]
                        else "",
                    )
                )
        verdict = _归纳(degraded_labels, labels)
        matrix_rows.append(
            "<tr><td>{0}</td>{1}<td class='verdict'>{2}</td></tr>".format(
                html.escape(_key_label(key, level)), "".join(cells), html.escape(verdict)
            )
        )
    if not matrix_rows:
        matrix_rows.append(
            "<tr><td colspan='{0}' class='empty'>各候选均未发现超过阈值的劣化项</td></tr>".format(
                len(labels) + 2
            )
        )

    head_cells = "".join("<th>{0}</th>".format(html.escape(label)) for label in labels)

    details = []
    for index, label in enumerate(labels):
        entries = per_candidate[index]
        body = _table_rows(entries, level) if entries else (
            "<tr><td colspan='4' class='empty'>未发现超过阈值的劣化项</td></tr>"
        )
        details.append(
            """
  <h3>{0}</h3>
  <table>
    <thead><tr><th style="width:56px">序号</th><th>{1}</th>
    <th style="width:110px">方向</th><th style="width:190px">劣化程度</th></tr></thead>
    <tbody>{2}</tbody>
  </table>""".format(
                html.escape(label), html.escape(_水平头[level]), body
            )
        )

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>性能测试结果对比报告（多版本）</title>
<style>
  :root {{ --ink:#1f2733; --muted:#6b7684; --line:#e3e8ef; --severe:#c0392b; --obvious:#e67e22; --slight:#c9a227; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:32px 20px 60px; background:#f6f8fb; color:var(--ink);
         font:15px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width: 1080px; margin: 0 auto; }}
  header {{ background:linear-gradient(135deg,#1f4e79,#2e75b6); color:#fff; border-radius:14px;
            padding:26px 30px; box-shadow:0 8px 24px rgba(31,78,121,.18); }}
  header h1 {{ margin:0 0 6px; font-size:24px; }}
  header .sub {{ opacity:.9; font-size:14px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:14px; margin:20px 0; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px 18px; }}
  .card .k {{ color:var(--muted); font-size:13px; }}
  .card .v {{ font-size:26px; font-weight:700; margin-top:4px; }}
  section {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:22px 24px; margin-bottom:18px; }}
  h2 {{ font-size:17px; margin:0 0 14px; padding-left:10px; border-left:4px solid #2e75b6; }}
  h3 {{ font-size:15px; margin:18px 0 10px; color:#2e75b6; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th,td {{ text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--muted); font-weight:600; background:#fbfcfe; }}
  tr:hover td {{ background:#fbfcfe; }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:12.5px; color:#fff; }}
  .g-severe {{ background:var(--severe); }}
  .g-obvious {{ background:var(--obvious); }}
  .g-slight {{ background:var(--slight); }}
  .amount {{ color:var(--muted); font-size:12.5px; }}
  .dash {{ color:#c3cad4; }}
  .verdict {{ color:#1f4e79; font-size:13px; }}
  .empty {{ color:var(--muted); text-align:center; padding:22px; }}
  .meta {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px 24px; font-size:14px; }}
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
    <h1>性能测试结果对比报告（多版本）</h1>
    <div class="sub">基线 {baseline} &nbsp;vs&nbsp; {cands} &nbsp;·&nbsp; 阈值 {threshold}</div>
  </header>

  <div class="cards">
    <div class="card"><div class="k">候选版本</div><div class="v">{count}</div></div>
    {cards}
  </div>

  <section>
    <h2>劣化矩阵</h2>
    <p style="color:#6b7684;font-size:13.5px;margin:0 0 12px">
      「结论」列含义：全部版本都劣化 = 持续问题；只有部分版本劣化 = 那些版本引入；先劣化后正常 = 已恢复。
    </p>
    <table>
      <thead><tr><th>{head_label}</th>{head_cells}<th>结论</th></tr></thead>
      <tbody>
{matrix_rows}
      </tbody>
    </table>
  </section>

  <section>
    <h2>按候选看明细</h2>
    {details}
  </section>

  <section>
    <h2>系统标识</h2>
    <div class="meta">
      <div><span class="k">基线</span><span>{baseline}</span></div>
      <div><span class="k">内核版本</span><span>{kernel}</span></div>
      <div><span class="k">劣化阈值</span><span>{threshold}</span></div>
      <div><span class="k">生成时间</span><span>{stamp}</span></div>
    </div>
  </section>

  <section>
    <h2>说明</h2>
    <p>每个候选都与<strong>同一个基线</strong>各比一次（不是相邻版本链式对比）。本报告<strong>不含任何具体测量值</strong>。</p>
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
        baseline=html.escape(baseline_label),
        cands=html.escape("、".join(labels)),
        threshold=html.escape(_标(threshold, "{}%")),
        count=len(labels),
        cards=cards,
        head_label=html.escape(_水平头[level]),
        head_cells=head_cells,
        matrix_rows="\n".join(matrix_rows),
        details="".join(details),
        kernel=html.escape(_标(info.get("baseline_kernel"))),
        stamp=html.escape(stamp),
        prompt=html.escape(_multi_prompt(per_candidate, labels, baseline_label, info, level)),
    )


def _multi_prompt(per_candidate, labels, baseline_label, info, level):
    totals = [len(entries) for entries in per_candidate]
    lookups = [_lookup(entries, level) for entries in per_candidate]
    lines = [
        "你是一名性能工程专家。以下是某次性能测试的多版本对比结论（数据已脱敏，不含测量值）：",
        "基线：{0}；候选：{1}".format(baseline_label, "、".join(labels)),
        "各候选劣化项数：{0}".format(
            "、".join("{0} {1} 项".format(label, total) for label, total in zip(labels, totals))
        ),
        "劣化矩阵（项 / 各候选程度 / 归纳）：",
    ]
    for key in _matrix_keys(per_candidate, level):
        cells, degraded_labels = [], []
        for index, label in enumerate(labels):
            entry = lookups[index].get(key)
            if entry is None:
                cells.append("—")
            else:
                degraded_labels.append(label)
                cells.append(entry["amount"] or entry["grade"])
        lines.append(
            "  · {0}：{1}（{2}）".format(
                _key_label(key, level), " / ".join(cells), _归纳(degraded_labels, labels)
            )
        )
    lines += [
        "请据此输出：① 哪些是长期存在的持续问题、哪些是某个版本新引入的回归；",
        "② 各问题可能的共性原因；③ 按影响面与严重程度排序的排查优先级；④ 建议的验证方式。",
        "注意：不要编造任何具体测量数值。",
    ]
    return "\n".join(lines)
