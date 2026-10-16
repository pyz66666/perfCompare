"""结果目录加载：把一个结果目录里的结果文件解析成可查询的测量值集合。

对外只暴露 `load(directory) -> ResultSet`；文件发现、噪声过滤、套与文件的映射、
按格式族分派解析器都藏在实现内部。

契约（见 CONTEXT.md）：测量值以 (测试套, 测试项, 子项) 三级定位。
"""
import json
import os
import re

from .spark_items import SPARK_ITEMS

# 测试套 → (子目录, 文件名, 解析器)。目前接入长表族的六个基础套 + 日志正则族的 mysql_tpcc；
# 其余套（SPEC CPU2017 CSV、场景化 JSON / 分组文本 / 裸数字列）在后续任务里逐个加入。
# 注意 unixbench 的文件名带一个前导空格 —— 这是上游产物的真实情况，不要"顺手修掉"。
_SUITE_FILES = {
    "stream": ("基础性能测试", ("stream.txt",), None),
    "fio": ("基础性能测试", ("fio.txt",), None),
    "iozone3": ("基础性能测试", ("iozone3.txt",), None),
    "lmbench3": ("基础性能测试", ("lmbench3.txt",), None),
    "netperf": ("基础性能测试", ("netperf.txt",), None),
    "unixbench": ("基础性能测试", (" unixbench-master.txt",), None),
    "mysql_tpcc": ("场景化测试", ("mysql_tpcc.txt",), "tpmc_log"),
    "nginx": ("场景化测试", ("nginx.json",), "nginx_json"),
    "flink_nexmark": ("场景化测试", ("flink_nexmark.json",), "flink_json"),
    "redis_docker": ("场景化测试", ("redis_docker.txt",), "redis_docker"),
    "mysql_sysbench": ("场景化测试", ("mysql_sysBench.txt",), "mysql_sysbench"),
    "flink_wordcount": ("场景化测试", ("flink_wordcount.json",), "flink_json"),
    "flink_6000c": ("场景化测试", ("flink_6000c.txt",), "flink_6000c"),
    "spark": ("场景化测试", ("spark.out",), "spark"),
    # speccpu2017 是**四个独立测试套**（需求方 2026-10-16）：int/fp × single/max。
    "speccpu2017_int_single": ("基础性能测试", ("cpu2017_int_single.txt",), "speccpu"),
    "speccpu2017_int_max": ("基础性能测试", ("cpu2017_int_max.txt",), "speccpu"),
    "speccpu2017_fp_single": ("基础性能测试", ("cpu2017_fp_single.txt",), "speccpu"),
    "speccpu2017_fp_max": ("基础性能测试", ("cpu2017_fp_max.txt",), "speccpu"),
    # 一套对多文件：三个文件各代表一个 docker。
    "spark_docker": (
        "场景化测试",
        ("spark_docker.out0", "spark_docker.out1", "spark_docker.out2"),
        "spark_docker",
    ),
}


class ResultSet:
    """一个结果目录里的全部测量值。"""

    def __init__(self, suites):
        self._suites = suites

    def value(self, suite, item, sub_item):
        """取某个 (测试套, 测试项, 子项) 上的测量值。"""
        return self._suites[suite][item][sub_item]

    def observations(self):
        """遍历全部测量值，按稳定顺序产出 (套, 测试项, 子项, 值)。"""
        for suite in sorted(self._suites):
            for item in sorted(self._suites[suite]):
                for sub_item in sorted(self._suites[suite][item]):
                    yield suite, item, sub_item, self._suites[suite][item][sub_item]


def expected_suites():
    """本工具认识的全部测试套名（用于诊断「哪些套没读到」）。"""
    return sorted(_SUITE_FILES)


def load(directory):
    """读取结果目录，返回 ResultSet。"""
    return load_with_report(directory)[0]


def load_with_report(directory):
    """读取结果目录，返回 `(ResultSet, 诊断信息)`，只解析一次。

    诊断信息是 `[(套名, 找到的文件路径或 None, 解析出的测量值条数, 该套的解析结果)]`，
    用于向用户说清「哪个套读到了、哪个文件在但格式不符、哪个文件根本没有」。
    区分后两者很重要：笼统说「未找到」会让用户无法判断是文件没生成还是格式变了。
    """
    suites = {}
    report = []
    for suite, (sub_dir, file_names, parser_name) in sorted(_SUITE_FILES.items()):
        paths = _locate_all(directory, sub_dir, file_names)
        if not paths:
            report.append((suite, None, 0, None, []))
            continue
        parsed = _PARSERS[parser_name](paths)
        suites[suite] = parsed
        report.append(
            (
                suite,
                paths[0],
                sum(len(subs) for subs in parsed.values()),
                parsed,
                _file_notes(paths[0]),
            )
        )
    return ResultSet(suites), report


# 结果文件里出现这些标记时给出提示（需求方 2026-10-16 确认要告警）：
# `INVALID RUN` 表示该次运行的结果不可报告，汇总值只是估计值。
_FILE_MARKERS = (
    ("INVALID RUN", "INVALID RUN（汇总值为估计值，不可作为可报告结果）"),
)


def _file_notes(path):
    """扫描结果文件里的已知告警标记，返回提示文案列表。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return []
    return [message for marker, message in _FILE_MARKERS if marker in text]


def _locate_all(directory, sub_dir, file_names):
    """定位一个测试套需要的**全部**结果文件；先试类别子目录，再试平铺。

    只要有一个文件找不到就返回空 —— 缺文件的套数据不完整，比对没有意义
    （例如 spark_docker 需要三个 docker 的文件齐全才能算平均值）。
    """
    paths = []
    for file_name in file_names:
        path = _locate(directory, sub_dir, file_name)
        if path is None:
            return []
        paths.append(path)
    return paths


def _locate(directory, sub_dir, file_name):
    """定位一个结果文件；先试类别子目录，再试平铺。找不到返回 None。"""
    for relative in (os.path.join(sub_dir, file_name), file_name):
        path = os.path.join(directory, relative)
        if os.path.isfile(path):
            return path
    return None


def _parse_tpmc_log(path):
    """从 jTPCC 日志里取出 tpmC：`Measured tpmC (NewOrders) = <值>`。

    该文件只有一行日志，没有测试项与子项的结构，故用空字符串作为子项名。
    """
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r"Measured tpmC \(NewOrders\)\s*=\s*([0-9.]+)", text)
    if match is None:
        return {}
    return {"tpmC": {"": float(match.group(1))}}


def _parse_long_table(path):
    """解析「长表」格式：测试项名 + 子项标签一行，average 一行，variance 一行。

    variance 行被忽略：首版只以 average 作为劣化判定依据。
    """
    with open(path, encoding="utf-8") as handle:
        lines = [line.strip() for line in handle]
    lines = [line for line in lines if line]

    items = {}
    labels = None
    for line in lines:
        if line.startswith("average"):
            if labels is None:
                continue
            values = [float(text) for text in line.split()[1:]]
            items[labels[0]] = dict(zip(labels[1:], values))
            labels = None
        elif line.startswith("variance"):
            labels = None
        else:
            labels = line.split()
    return items


def _parse_nginx_json(path):
    """`nginx.json`：一条记录里带 `workload_data[]`，每个 workload 的 performance_data 是一个值。

    ⚠️ 记录**顶层**的 `performance_data`（样例 234564.88）**不读取** —— 需求方要求汇总
    由四个 workload 自己求几何平均（与顶层值不同，见规划文档 8. nginx）。
    """
    with open(path, encoding="utf-8") as handle:
        records = json.load(handle)
    items = {}
    for record in records:
        for workload in record.get("workload_data", []):
            items[workload["name"]] = {"": float(workload["performance_data"])}
    return items


def _parse_flink_json(path):
    """flink 系列 JSON：每条记录 = 一个 testcase，`performance_data` 即该用例的值。

    ⚠️ 该字段在样例里有时是数字、有时是字符串（事实 F7），统一转成 float。
    没有 `testcase_name` 的记录跳过。
    """
    with open(path, encoding="utf-8") as handle:
        records = json.load(handle)
    items = {}
    for record in records:
        name = record.get("testcase_name")
        if name is None:
            continue
        items[name] = {"": float(record["performance_data"])}
    return items


def _parse_redis_docker(path):
    """`redis_docker.txt` 与长表同形，但**跳过文件自带的 `avg` 与 `geom` 两列**。

    `geom` 列在样例里与四个 docker 的几何平均并不一致（模拟数据假象），
    且需求方要求由四个 docker 自己算，故不采用自带列。
    """
    items = {}
    for item, subs in _parse_long_table(path).items():
        items[item] = {
            sub: value for sub, value in subs.items() if re.match(r"docker\d+$", sub)
        }
    return items


def _parse_mysql_sysbench(path):
    """`mysql_sysBench.txt`：一行测试项名，随后若干行 `<指标> v1 v2 v3 v4`。

    只取 `TPS` 指标，值为四次取值的**算术平均**；`95th_latency` 暂不显示（需求方确认）。
    """
    items = {}
    current = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if len(parts) == 1:
                current = parts[0]
                continue
            if current is None or parts[0] != "TPS":
                continue
            values = [float(text) for text in parts[1:]]
            items[current] = {"TPS": sum(values) / len(values)}
    return items


def _parse_flink_6000c(path):
    """`flink_6000c.txt` 是残缺片段：若干行 `"read-records": N,` 加末尾一个裸数字。

    只取 `read-records` 那几行，按出现顺序编号为子项；末尾那个裸数字**不参与**
    （需求方确认由三行求和取平均）。
    """
    values = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = re.search(r'"read-records":\s*([0-9.]+)', line)
            if match is not None:
                values.append(float(match.group(1)))
    return {"read-records": {str(index + 1): value for index, value in enumerate(values)}}


def _single(parser):
    """把「只处理一个文件」的解析器适配成统一的多文件接口。"""

    def adapted(paths):
        return parser(paths[0])

    return adapted


def _read_numbers(path):
    """读一列数字：每个非空行一个值。"""
    with open(path, encoding="utf-8") as handle:
        return [float(line) for line in handle if line.strip()]


def _parse_spark(paths):
    """`spark.out`：103 个测试项 × 3 轮 + 1 个汇总值。

    取值顺序是**轮次优先**：先 103 项的轮 1，再 103 项的轮 2，再轮 3，最后 1 个汇总值。
    汇总值是本次运行三轮的**合计**，按需求方口径 ÷3 得到单轮平均
    （见规划文档「对比项定义 15. spark」）。
    """
    values = _read_numbers(paths[0])
    count = len(SPARK_ITEMS)
    items = {}
    for index, name in enumerate(SPARK_ITEMS):
        rounds = [values[index + round_index * count] for round_index in range(3)]
        items[name] = {
            "轮1": rounds[0],
            "轮2": rounds[1],
            "轮3": rounds[2],
            "avg": sum(rounds) / len(rounds),
        }
    items["汇总"] = {"值": values[3 * count] / 3.0}
    return items


def _parse_spark_docker(paths):
    """`spark_docker.out0/1/2`：每个文件代表一个 docker，各含 103 项 + 1 个汇总值。

    每项给出三个 docker 的取值与它们的平均值（需求方口径：只对比平均值）。
    """
    per_docker = [_read_numbers(path) for path in paths]
    count = len(SPARK_ITEMS)
    items = {}
    for index, name in enumerate(SPARK_ITEMS):
        values = [numbers[index] for numbers in per_docker]
        entry = {
            "docker{0}".format(docker_index): value
            for docker_index, value in enumerate(values)
        }
        entry["avg"] = sum(values) / len(values)
        items[name] = entry
    items["汇总"] = {
        "docker{0}".format(docker_index): numbers[count]
        for docker_index, numbers in enumerate(per_docker)
    }
    return items


def _is_number(text):
    try:
        float(text)
    except ValueError:
        return False
    return True


def _parse_speccpu(paths):
    """SPEC CPU2017 ASCII 报告：各 benchmark 的选中分数 + 汇总行。

    四份文件（int/fp × single/max）各自是一个独立测试套，故各自解析。汇总行标签按类取
    `SPECrate2017_int_base`（整数）或 `SPECrate2017_fp_base`（浮点）。

    无效的 benchmark（状态 VE、分数 NR）**没有分数就跳过**，不伪造数据 —— 这是
    `INVALID RUN` 的后果之一（例如 fp 单核的 `507.cactuBSSN_r`）。
    """
    path = paths[0]
    summary_label = (
        "SPECrate2017_fp_base"
        if "fp" in os.path.basename(path)
        else "SPECrate2017_int_base"
    )
    items = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) == 5 and fields[4] == "*" and _is_number(fields[3]):
                # 各 benchmark 的选中行：`名称 副本数 运行时间 分数 *`
                items[fields[0]] = {"": float(fields[3])}
            elif len(fields) == 3 and fields[1] == summary_label and _is_number(fields[2]):
                # 汇总行：`Est. SPECrate2017_int_base   5.66`
                items[summary_label] = {"": float(fields[2])}
    return items


# 解析器注册表。统一接口：接收**文件路径列表**（单文件套只用一个）。
_PARSERS = {
    None: _single(_parse_long_table),
    "tpmc_log": _single(_parse_tpmc_log),
    "nginx_json": _single(_parse_nginx_json),
    "flink_json": _single(_parse_flink_json),
    "redis_docker": _single(_parse_redis_docker),
    "mysql_sysbench": _single(_parse_mysql_sysbench),
    "flink_6000c": _single(_parse_flink_6000c),
    "spark": _parse_spark,
    "spark_docker": _parse_spark_docker,
    "speccpu": _parse_speccpu,
}
