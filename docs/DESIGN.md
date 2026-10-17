# 数据处理 Skill — 架构设计文档（v0.1 设计稿）

> 目标：用户把 skill 下载下来后，对任何数据都有 Agent 来判断它是什么方法，先把基本的数据清理做一遍，再按 Nature 级别处理干净，最后写成报告和图表返回给用户。

---

## 1. 四大设计原则

1. **additive-only** — 永远不修改、删除、移动用户的原始数据。所有产物写到 dataset/cleaned/ 与 dataset/analysis/。
2. **never-automatic 列表** — 高风险操作永远只标记给人类决策（删除行、impute 缺失、删除异常、修改原始列名、合并数据集、对外发布）。这些动作绝不静默执行。
3. **method provenance** — 每个决策都能追溯到 (a) 内置规则目录、(b) 脚本输出、(c) web research 三种来源之一，并写入报告。
4. **data integrity** — 类型由 plan 决定一次，不得在读取阶段推断；未经 plan 授权的列不得出现新值。详见 § 1.1。

### 1.1 数据完整性契约（第三条原则是第四条的技术形式）

这不是额外的保守选项，而是“Agent 代替人做决定”这一核心前提下的必然结果。四条子契约：

**(a) 读取不是类型推断。** CSV / TSV / Excel 统一以 `dtype=str` 读入
（`dm_types.read_table(..., read_mode="text")`），JSON / Parquet 因为 schema 已声明类型而豁免。
保真的原因：`pd.read_csv` 会把邮编 `02134` 变成 `2134`，与真实存在的 `2134`
合并。这个错误发生在**任何审计存在之前**，所以引导零对三个对象同时失存：
前导零本身、“做过决策”的证据、以及从输出回溯可能性的任何位置。

**(b) 转换是全有全无（all-or-nothing），其余全部交给人。**
只有**每一个**非空值都能解析时才转换。不存在解析率阈值：
阈值不会让决策更安全，它只是选择静默地销毁多少。存在四类 hold，
每类都带证据交给用户而非阻断流程：`leading_zero` / `currency_or_rate` / `numeric_or_date` / `mixed_with_text`（见
[`cleaning-rule-catalog.md`](../references/cleaning-rule-catalog.md)）。

**(c) 类型决定一次，经 manifest 重放。** `cleaning_run.json` 记录 `dtype_manifest`，
下游一律重放而不重新猜测；若 manifest 缺失则标注为 guess 并附 warning。

**(d) 未经授权的列不得出现新值。** `audit_untouched_columns()` 对每个未被 plan 点名的列做字节级比对；
空白卫生操作（strip / collapse / NFC / quotes）由 `hygiene_project` 精确重放后对比，因此该检查非空浮。
安全默认是**“未知操作一律受审”** —— `VALUE_CHANGING_OPS` 显式枚举允许改值的操作。

> 实例：一版实现中 profiler 按文本模式读入，而 cleaning 阶段用 pandas 默认值重读一次，静默销毁了邮编列。
> plan 写着“keep as text”，report 显示无变化，而文件里已经没有任何决策证据可恢复。
> 现在 `tests/test_pipeline_invariants.py` 把它固化为一个失败就报错的回归测试，包括一个**必须失败**的负向对照。

---

## 2. 三阶段流水线

```
[Stage 1: Detect & Clean]              [Stage 2: Analyze (Nature)]              [Stage 3: Deliver]
─────────────────────────              ───────────────────────────              ─────────────────────
data-router            (模态识别)        data-explorer            (EDA)           visualizer            (图表)
  ↓                                     ↓                                          ↓
data-profiler          (画像)           data-validator           (质量门)         report-generator      (报告)
  ↓                                     ↓                                          ↓
data-cleaner           (清理)           data-transformer         (转换)           dashboard-builder     (仪表盘)
                                        ↓
                                        statistical-analyzer    (描述+推断)
                                        ↓
                                        deep-analyzer           (建模/因果/预测)
```

每个 Stage 都有 gate（参考 my-mathmodel-agent 的 default-FAIL contract）。Gate 失败的产物被冻结到 audit/，可被人工修复后重新进入流水线。

---

## 3. Skill 拆分（10 个子 skill + 1 个路由）

| # | 子 skill | 输入 | 输出 | 核心职责 |
|---|---|---|---|---|
| 1 | data-router | 任意文件 / 路径 / glob / DataFrame | 模态 + 领域标签 + 路由表 | 把输入分到 [tabular, text-corpus, time-series, image-set, audio-set, geospatial, mixed, unknown] 八类之一 |
| 2 | data-profiler | 一份数据 + 模态标签 | profile.json | 确定性脚本输出画像：形状、dtypes、缺失率、重复率、分布、异常、相关性、领域特征 |
| 3 | data-cleaner | profile.json + 模态 | cleaning_plan.json + clean_*.py + cleaned/* | 基础清理；自动决定规则 + 标记 never-automatic 项；产出可重跑的脚本 |
| 4 | data-explorer | cleaned data | eda.json + eda_charts/*.png | 探索性分析：分布、相关、聚类、关键洞察候选 |
| 5 | data-validator | cleaned data + 领域规则 | validation_report.md + gates.json | Nature 级别的检查清单：n 定义、缺失机制、异常准则、抽样偏差、leakage |
| 6 | data-transformer | cleaned data + 模型需求 | transformed.csv | 标准化 / 编码 / 特征工程 / 时间对齐 / 文本向量化 |
| 7 | statistical-analyzer | 清理 + 转换后的数据 | stats.json | Nature 级统计：描述统计 + 推断检验 + 效应大小 + 置信区间 + 多重比较校正 + 缺失值敏感性 |
| 8 | deep-analyzer | 任务目标 + 清理后数据 | model.json + predictions/* | 按数据模态自适应选模型 |
| 9 | visualizer | stats.json + eda.json + model.json | charts/*.png + chart_decisions.json | 借鉴 himcm-chart-system 的 25 种图表 + 8 个复杂度原则 + 标题-说明-正文三段式 |
| 10 | report-generator | 上述所有 json | report.md + executive_summary.md | 借鉴 data-storytelling 的 setup→conflict→resolution 框架 + 6 段强制结构 + 至少一个 caveat |

辅助：
- **workspace-init** — 初始化运行目录、写 README、记录状态
- **state-keeper** — 状态文件 state.json（每个 gate 一次快照），使下次可 resume

---

## 4. Nature 级别处理的具体定义

参考本地 nature-statistics 的原则并落成可执行清单：

1. n 必须显式：区分 independent unit / technical replicate / repeated measure
2. 缺失机制必须分类：MCAR / MAR / MNAR，写到报告；任何 imputation 都标注方法和影响
3. 效应大小优先于 p 值：报告 Cohen d / Cliff delta / odds ratio + 95% CI
4. 不确定性必须可见：每张图带 CI / SE / 区间；每个数字带 CI
5. 多重比较必须校正：Bonferroni / BH / Holm 等
6. 敏感性分析：剔除 / 加入 / 替换 / 重采样下的结果稳定性
7. 不升级关联到机制：claim 必须限制在 supported evidence 之内
8. AUTHOR_INPUT_NEEDED：无法从数据推断的事实（盲法、随机化、伦理）必须明确标记

这些做成 validator skill 的检查清单，自动打分 + 提示未达标的项。

---

## 5. Agent 自动判断的透明化

每个阶段产物都是 JSON + Markdown，结构如下：

```json
{
  "step": "data-cleaner",
  "modality": "tabular",
  "judgments": [
    {
      "issue": "column age has 12% missing",
      "decision": "impute with median",
      "rule_source": "references/cleaning-rule-catalog.md#numeric-5-30-percent",
      "alternative_considered": ["drop column", "KNN imputation"],
      "rejected_reason": "KNN would distort univariate stats",
      "never_automatic_flag": false
    },
    {
      "issue": "3 rows have negative units_sold",
      "decision": "flag for manual review (do not drop)",
      "rule_source": "references/never-automatic-list.md#sales-negative",
      "never_automatic_flag": true
    }
  ]
}
```

每一段判断都进报告的 Method Provenance 段，附原文引用与拒绝理由。

---

## 6. 目录结构（实时状态）

标记：`[✓]` 已实现并有回归测试 / `[○]` 未实现。你下载的是本文档所列的目录，
未标记的文件不存在。

```
data-master/
├── SKILL.md                       [✓] 主路由：3 阶段总览 + 数据完整性契约四条
├── docs/DESIGN.md                 [✓]
├── references/
│   ├── modality-routing.md        [✓] 8 类模态路由表
│   ├── cleaning-rule-catalog.md   [✓] 含四类 hold 与“读取不是类型推断”
│   ├── never-automatic-list.md    [✓]
│   ├── nature-statistics-checklist.md  [✓] 8 道 Nature gate
│   ├── chart-decision-catalog.md  [✓] 参数任务 → 图表映射 + 8 条复杂度原则
│   ├── workflow-contract.md       [✓] 逐步契约与 gate
│   ├── research-protocol.md      [✓] 未知格式调研协议
│   ├── report-template-catalog.md[✓]
│   ├── ── story-frameworks.md        [○] 报告故事化框架
│   ├── ── effect-size-guide.md       [○] 已并入 stats_inferential.py
│   ├── ── missing-data-guide.md      [○]
│   └── ── sensitivity-guide.md       [○]
├── scripts/
│   ├── dm_types.py              [✓] 唯一权威类型层：read_table / manifest 重放 / 白卫重放
│   ├── check_deps.py             [✓]
│   ├── profile_tabular.py        [✓]
│   ├── cleaning_plan.py         [✓] schema 1.2
│   ├── execute_cleaning.py      [✓] 字节级可复现
│   ├── validate_clean.py        [✓] 6 gate + untouched-column 审计
│   ├── stats_descriptive.py     [✓]
│   ├── stats_inferential.py     [✓] ANOVA / Welch / Mann-Whitney / Kruskal
│   ├── effect_size.py            [✓] Cohen d / Cliff delta / omega^2 / Cramér V
│   ├── route_input.py          [✓] 扩展名 + 深度嗅探 → route.json
│   ├── profile_text.py         [✓] 重复文档 / 空文件 / 编码回退
│   ├── profile_timeseries.py   [✓] 间隔 / 缺口 / 采样制式变化 / ADF 筛查
│   ├── profile_media.py        [✓] 图像 aHash 近重复 + 音频削波/静音
│   ├── profile_geospatial.py   [✓] CRS / 越界 / null island / 重合点
│   ├── chart_decision.py       [✓] 一图一论点 + rejected 记录
│   ├── render_chart.py         [✓] 200 dpi + 墨迹比回读 + 标题不溢出
│   ├── assemble_report.py      [✓] report.md / report.pdf / report_build.json
│   ├── final_audit.py          [✓] 8 gate + 期刊清单 + structural checks
│   ├── _md2pdf_reportlab.py    [✓] PDF 一级后端（CJK / 目录 / 页码）
│   ├── _md2pdf_fpdf.py         [✓] 二级后端，已实测
│   ├── _md2pdf_browser.py      [✓] 三级后端（Edge headless）
│   ├── ── sensitivity_analysis.py         [○] 留一法等扰动尚未自动化
│   ├── state_keeper.py         [✓] 状态检查 / 冷恢复入口
│   ├── run_pipeline.py         [✓] 单命令执行器
│   └── pipeline_state.py       [✓] 状态与输入指纹
├── skills/                       [✓] 10 个子 skill，各绑定一个 stage + gate
├── references/
│   ├── journal-reporting-standards.json [✓] 机器可读路由表（9 design + generic）
│   └── journal-reporting-standards.md   [✓] NEJM / Science / Lancet / Nature
├── tests/test_pipeline_invariants.py [✓] 33 项，零依赖，含负向对照
├── examples/
│   ├── iris/            [✓] 158×8，两条 ANOVA 分支 + 完整 PDF 报告
│   ├── column_traps/     [✓] 240×10，每列一类转换陷阱
│   ├── timeseries/       [✓] 缺口 + 重传 + 采样制式变化
│   ├── text/             [✓] 重复文档 + 空文件 + GB18030
│   ├── media/            [✓] 损坏图 + 重编码近重复 + 空白帧
│   └── geo/              [✓] 经纬度互换 + null island + 空坐标
└── docs/assets/            [✓] README 报告截图
```

> Stage 1（路由 + 6 类模态画像）、Stage 2（统计 + Welch 分母自由度）、Stage 3
> （图表 + PDF 报告 + 8 gate 审计）已经贯通。`run_pipeline.py` 提供单命令入口和
> 可验证的冷恢复；未完成的是敏感性分析的留一法自动化，以及非表格模态的推断分析。

---

## 7. 借鉴与差异

| 借鉴来源 | 学到的 | 我们的差异 |
|---|---|---|
| yogaibhh/claude-clean-data-skill | 8 步流水线 + 路由表 + 规则目录 + profiler | 我们加上 Stage 2 (Nature 分析) + Stage 3 (报告交付) |
| Votee-AI/magic-data-agent-skills | 12 层 skill 分工 | 我们合并为 10 层；强调 nature 级别 |
| Chen-barber/scientific-analysis-skill | 编号脚本顺序 | 我们抽象为通用流水线 + 模态子流水线 |
| nature-statistics | n / 效应大小 / CI / 缺失机制 / 透明度 | 直接作为 validator skill 的内核 |
| himcm-chart-system | 25 种图表 + 复杂度原则 | 直接作为 visualizer skill 的内核 |
| data-storytelling | setup→conflict→resolution | 直接作为 report-generator skill 的内核 |
| my-mathmodel-agent | state 化 + gate + default-FAIL | 我们加 state-keeper 做 cold-resume |
| hackathon-run | 每个 skill 独立可用 | 同样设计原则 |
| K-Dense-AI/scientific-agent-skills (51K stars) | 工具级 skill 矩阵 | 我们聚焦通用数据处理流水线，不重复工具级 skill |

---

## 8. 设计决策（用户已定，不再重新讨论）

| # | 问题 | 决定 | 对架构的影响 |
|---|---|---|---|
| 1 | 单 skill 还是多 skill | **多 skill：`data-master` 路由 + 10 子 skill** | 模态之间分析逻辑差异太大，单 skill 会变成无法独立测试的大文件 |
| 2 | Nature 标准的来源 | **既有 8 条可自动判定的 gate，再加 NEJM / Science / Lancet 的报告标准** | 新增 `references/journal-reporting-standards.md`；报告器需支持按研究设计选择清单 |
| 3 | 目标用户 | 研究人员优先，业务场景降级到 `standard` 模板 | 三套报告模板 |
| 4 | 模态覆盖 | **通用，全部并行（不限 tabular）** | 7 类模态各自完成 profile → clean → analyze → deliver，共用一套契约与交付层 |
| 5 | 交付形式 | **PDF 报告** | Stage 3 的主产物是 `.pdf`；Markdown 保留为可引用的源文本 |
| 6 | 是否对外发布 | **GitHub 公开仓库** | 需要 LICENSE / README / CONTRIBUTING / CI / 安全声明 |
| 7 | 命名 | **`data-master`** | 目录名与主 SKILL.md 名定稿 |

### 关键取舍（不可推翻）

1. **additive-only**：原始数据永远不改动
2. **三阶段 + gate**：default-FAIL contract，gate 失败的产物冻结到 `audit/`
3. **三元 provenance**：`rule_source + alternative_considered + rejected_reason`
4. **plan 即 gate**：只执行 `plan["auto_actions"]`，`never_automatic_flags` 一律不执行
5. **无任何解析率阈值**：all-or-nothing；阈值只是选择销毁多少
6. **正态性不否决参数检验**（n≥30）；方差不等走 Welch
7. **字节级可复现性**已内建于 `execute_cleaning.py`
8. **读取阶段不得推断类型**（CSV/TSV/Excel 一律 `dtype=str`）
9. **类型决定一次、manifest 重放**，绝不二次猜测
10. **稀释转换不得进入多重比较族**：一个 NaN p 值会通过累积最小值把整族的校正后 p 值全部污染成 NaN
11. **不可估计就不报 p 值**：退化组、常数分组的 outcome、分组变量的同义重复——返回 `None` + 原因，而不是 NaN

---

## 9. 下一步（按优先级）

**P0 — PDF 交付闭珨**（用户已指定的交付形式）
1. `chart_decision.py` → `render_chart.py`（图表）
2. `assemble_report.py` → `report.md` → `report.pdf`（含图表嵌入与页码）
3. `final_audit.py`（对报告做最后审计）

**P1 — 期刊报告标准**
4. `references/journal-reporting-standards.md`：NEJM / Science / Lancet 的可机检清单，
   按研究设计（随机试验 / 观察研究 / 系统评价 / meta 分析）选对应清单

**P2 — 模态并行**（用户已指定全部并行）
5. `profile_text.py` / `profile_timeseries.py` / `profile_media.py` / `profile_geospatial.py`
6. 各模态的 cleaning 规则扩展 + 分析方法对应表

**P3 — 发布**（GitHub 公开）
7. LICENSE / README / CONTRIBUTING / 安全声明 / CI

