"""结果目录加载：把一个结果目录里的结果文件解析成可查询的测量值集合。

对外只暴露 `load(directory) -> ResultSet`；文件发现、噪声过滤、套与文件的映射、
按格式族分派解析器都藏在实现内部。

契约（见 CONTEXT.md）：测量值以 (测试套, 测试项, 子项) 三级定位。
"""
import json
import os
import re

# 测试套 → (子目录, 文件名, 解析器)。目前接入长表族的六个基础套 + 日志正则族的 mysql_tpcc；
# 其余套（SPEC CPU2017 CSV、场景化 JSON / 分组文本 / 裸数字列）在后续任务里逐个加入。
# 注意 unixbench 的文件名带一个前导空格 —— 这是上游产物的真实情况，不要"顺手修掉"。
_SUITE_FILES = {
    "stream": ("基础性能测试", "stream.txt", None),
    "fio": ("基础性能测试", "fio.txt", None),
    "iozone3": ("基础性能测试", "iozone3.txt", None),
    "lmbench3": ("基础性能测试", "lmbench3.txt", None),
    "netperf": ("基础性能测试", "netperf.txt", None),
    "unixbench": ("基础性能测试", " unixbench-master.txt", None),
    "mysql_tpcc": ("场景化测试", "mysql_tpcc.txt", "tpmc_log"),
    "nginx": ("场景化测试", "nginx.json", "nginx_json"),
    "flink_nexmark": ("场景化测试", "flink_nexmark.json", "flink_json"),
    "redis_docker": ("场景化测试", "redis_docker.txt", "redis_docker"),
    "mysql_sysbench": ("场景化测试", "mysql_sysBench.txt", "mysql_sysbench"),
    "flink_wordcount": ("场景化测试", "flink_wordcount.json", "flink_json"),
    "flink_6000c": ("场景化测试", "flink_6000c.txt", "flink_6000c"),
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
    suites = {}
    for suite, (sub_dir, file_name, parser_name) in _SUITE_FILES.items():
        path = os.path.join(directory, sub_dir, file_name)
        if os.path.isfile(path):
            suites[suite] = _PARSERS[parser_name](path)
    return ResultSet(suites)


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


# 解析器注册表。`_SUITE_FILES` 里用名字引用，避免在定义处前向引用函数。
_PARSERS = {
    None: _parse_long_table,
    "tpmc_log": _parse_tpmc_log,
    "nginx_json": _parse_nginx_json,
    "flink_json": _parse_flink_json,
    "redis_docker": _parse_redis_docker,
    "mysql_sysbench": _parse_mysql_sysbench,
    "flink_6000c": _parse_flink_6000c,
}
