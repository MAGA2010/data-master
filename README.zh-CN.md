# data-master

**一条命令，把杂乱数据变成可审计、可复现的 PDF 分析报告。**

[English](README.md) · [案例](README.md#reproducible-case-studies) · [评估证据](EVALUATION.md) · [路线图](ROADMAP.md)

![data-master 从原始数据生成可核验报告](docs/assets/demo.gif)

`data-master` 同时是 Codex Skill 和跨平台命令行工具。它保留原始数据、显式记录清洗决策、按真实独立单位运行统计分析、执行敏感性检查，并交付 Markdown、PDF 与机器可读证据。

## 快速体验

需要 Node.js 20+ 和 Python 3.11+：

```bash
npm install -g github:MAGA2010/data-master#v0.2.0
data-master setup
data-master skill install
data-master demo --out outputs/first-demo
```

打开 `outputs/first-demo/report.pdf` 阅读报告，再查看
`outputs/first-demo/audit/final_audit.md` 的审计结论。

npm 包没有安装钩子，也没有 JavaScript 依赖。只有显式运行 `setup` 才会下载 Python 依赖并创建隔离环境；`skill install` 会原子化安装 Skill，若目标目录已存在则拒绝覆盖。

## 核心价值

- CSV/TSV 默认按文本读取，避免邮编、编号等被静默改写；
- 所有类型转换都进入清洗计划，无法安全判断时要求人工回答；
- 通过 `--unit-key` 识别重复测量，避免把多行当成多个独立样本；
- p 值与样本量、检验名称、自由度、效应量和区间同时记录；
- 敏感性分析、报告与最终审计都有独立的机器可读证据；
- 断点续跑前核验文件哈希、代码、依赖与运行参数。

分析自己的数据：

```bash
data-master analyze measurements.csv \
  --out outputs/study \
  --group treatment \
  --unit-key participant_id \
  --outcomes response_time,accuracy
```

当前完整推断流程适用于单个表格文件；时间序列模式只做描述性统计，不做预测；文本、图像、音频、地理与混合输入生成明确标注的画像报告。完整安装方法、案例、限制和贡献方式请阅读[英文主文档](README.md)。

项目采用 [MIT License](LICENSE)。
