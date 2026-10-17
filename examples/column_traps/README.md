# column_traps — 每一列都是一类转换陷阱

这个示例不是一个真实数据集。它是一个 **240 × 10 的训练场**，每一列被特意构造成
某一类“看起来能转换、但转之后意思已经变了”的错误。它存在的目的是让管线能被测试持续打磨。

## 构造的陷阱

| 列 | 原始值 | 无脚转换的结果 |
|---|---|---|
| `postcode` | `02134`, `30302`, `10002` | 引导零被吃掉，与真实的 `2134` 合并 |
| `revenue` | `$1,200`, `€980` | 去掉币种符号后才能解析，且“去符号”与“除以 100”给出不同数字 |
| `growth_pct` | `12%`, `-3%` | 同上 |
| `signup_date` | `2024-01-15`, 一致 | 孤立转换（它不是陷阱，用来对照） |
| `mostly_text` | 158 个值里 5 个是 `--`，24 个是 `unknown` | 部分值变 NaN，“未记录”与“从未采集”不可区分 |
| `region` | 16 种大小写变体 | 变体是同一地理区仍资料性消失（**损失性**，可自动合并） |
| `phone` | 带国徽空格与括号 | 空白卫生问题（应自动修） |

## 跑流程

```bash
python examples/column_traps/make_traps.py          # 重建训练场（确定性，seed 固定）

python scripts/profile_tabular.py --in examples/column_traps/traps_dirty.csv \
    --out examples/column_traps/outputs/analysis/profile.json

python scripts/cleaning_plan.py --profile examples/column_traps/outputs/analysis/profile.json \
    --out examples/column_traps/outputs/cleaning_plan.json

python scripts/execute_cleaning.py --in examples/column_traps/traps_dirty.csv \
    --plan examples/column_traps/outputs/cleaning_plan.json \
    --out examples/column_traps/outputs/cleaned

python scripts/validate_clean.py --raw examples/column_traps/traps_dirty.csv \
    --clean examples/column_traps/outputs/cleaned/cleaned.csv \
    --profile examples/column_traps/outputs/analysis/profile.json \
    --out examples/column_traps/outputs/cleaned/validation.json
```

四步之间不得插入手工步骤：每一步的输出都是下一步唯一的输入。

## 结果（已核对）

**11 项自动动作 / 5 项 never-automatic 标记**

自动转换恰好只有两列数字和一列日期 —— 而且每一列都是满足“每个非空值都能解析”：

```
coerce_numeric  -> turnover, weight_kg
coerce_dates    -> signup_date
```

四类 hold 全部触发，并且每类都带了证据：

```
leading_zero     -> postcode      02134 存活
currency_or_rate -> revenue, growth_pct   $ / % 原样保留
mixed_with_text  -> mostly_text   24 个 unknown 与 5 个 -- 原样保留
```

`region` 的大小写合并是第五个标记中的一个，它不在“可自动做”的列：16 → 4，
且完整的合并映射写入 `cleaning_run.json`，任何层级可逐字恢复。

**字节级可复现**：`cleaning_run.json` 里的 `reproducibility_check.passed = true`，
重生脚本 `clean_traps_dirty.py` 的产物与 `cleaned.csv` 的 SHA-256 相同。

**untouched 审计通过**：`columns_checked = 6`，即 `postcode` / `phone` / `revenue` / `growth_pct` /
`mostly_text` / `batch_code` 六列没有任何操作点名，它们完整保留了原值。
`postcode` 在这深容了这个断言 —— `02134` 存在于输出。

## 这个示例守住的约定

`tests/test_pipeline_invariants.py` 直接对这份数据运行，并包含一个**必须失败**的负向对照：
把旧的有缺陷读取器传进审计，审计必须 FAIL 并点名 `postcode`。如果它通过了，
说明审计已经失效。

```bash
python tests/test_pipeline_invariants.py
```
