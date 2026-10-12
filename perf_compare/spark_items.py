"""spark 测试套的测试项名单。

来源：需求方 2026-10-12 提供。**顺序即结果文件里的取值顺序**，不可重排。

规模已与样例数据核对过：

- `spark.out`：103 × 3 轮 + 1 个汇总 = 310 个值；
- `spark_docker.out0/1/2`：各 103 + 1 个汇总 = 104 个值（每个文件代表一个 docker）。

其中 8 个项带 a/b 后缀：q14、q23、q24、q39。
"""
SPARK_ITEMS = (
    "native_q1", "native_q2", "native_q3", "native_q4", "native_q5", "native_q6",
    "native_q7", "native_q8", "native_q9", "native_q10", "native_q11", "native_q12",
    "native_q13", "native_q14a", "native_q14b", "native_q15", "native_q16",
    "native_q17", "native_q18", "native_q19", "native_q20", "native_q21",
    "native_q22", "native_q23a", "native_q23b", "native_q24a", "native_q24b",
    "native_q25", "native_q26", "native_q27", "native_q28", "native_q29",
    "native_q30", "native_q31", "native_q32", "native_q33", "native_q34",
    "native_q35", "native_q36", "native_q37", "native_q38", "native_q39a",
    "native_q39b", "native_q40", "native_q41", "native_q42", "native_q43",
    "native_q44", "native_q45", "native_q46", "native_q47", "native_q48",
    "native_q49", "native_q50", "native_q51", "native_q52", "native_q53",
    "native_q54", "native_q55", "native_q56", "native_q57", "native_q58",
    "native_q59", "native_q60", "native_q61", "native_q62", "native_q63",
    "native_q64", "native_q65", "native_q66", "native_q67", "native_q68",
    "native_q69", "native_q70", "native_q71", "native_q72", "native_q73",
    "native_q74", "native_q75", "native_q76", "native_q77", "native_q78",
    "native_q79", "native_q80", "native_q81", "native_q82", "native_q83",
    "native_q84", "native_q85", "native_q86", "native_q87", "native_q88",
    "native_q89", "native_q90", "native_q91", "native_q92", "native_q93",
    "native_q94", "native_q95", "native_q96", "native_q97", "native_q98",
    "native_q99",
)
