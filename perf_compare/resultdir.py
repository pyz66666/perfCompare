"""结果目录加载：把一个结果目录里的结果文件解析成可查询的测量值集合。

对外只暴露 `load(directory) -> ResultSet`；文件发现、噪声过滤、套与文件的映射、
按格式族分派解析器都藏在实现内部。

契约（见 CONTEXT.md）：测量值以 (测试套, 测试项, 子项) 三级定位。
"""
import os

# 测试套 → (子目录, 文件名)。首版只接长表族的 fio，其余套在后续任务里逐个加入。
_SUITE_FILES = {
    "fio": ("基础性能测试", "fio.txt"),
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


def load(directory):
    """读取结果目录，返回 ResultSet。"""
    suites = {}
    for suite, (sub_dir, file_name) in _SUITE_FILES.items():
        path = os.path.join(directory, sub_dir, file_name)
        if os.path.isfile(path):
            suites[suite] = _parse_long_table(path)
    return ResultSet(suites)


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
