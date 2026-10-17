# iris — 从脏数据到 Nature 级统计的完整链路

这是一个回归用例：经过变异化的花蓝衣集，7528来验证流水线在**正常数据**
上会怎么行。`column_traps` 负责证明它不会破坏数据，这个负责证明它能完整地做统计。

## 构造的脏数据

`make_dirty_iris.py` 在原始 150 行基础上添加了类型异常，使其为 158 × 8：

- 带的但不可解析的 `notes` 列（全空 → 应自动丢弃）
- `height_m` 的带前导零值（应 hold，不自动转数字）
- `species` 的大小写变体
- `petal_width_cm` / `sepal_width_cm` 的缺失值

## 跑流程

```bash
python examples/iris/make_dirty_iris.py

python scripts/profile_tabular.py --in examples/iris/iris_dirty.csv \
    --out examples/iris/outputs/analysis/profile.json

python scripts/cleaning_plan.py --profile examples/iris/outputs/analysis/profile.json \
    --out examples/iris/outputs/cleaning_plan.json

python scripts/execute_cleaning.py --in examples/iris/iris_dirty.csv \
    --plan examples/iris/outputs/cleaning_plan.json \
    --out examples/iris/outputs/cleaned

python scripts/validate_clean.py --raw examples/iris/iris_dirty.csv \
    --clean examples/iris/outputs/cleaned/cleaned.csv \
    --profile examples/iris/outputs/analysis/profile.json \
    --out examples/iris/outputs/cleaned/validation.json

python scripts/stats_descriptive.py --clean examples/iris/outputs/cleaned/cleaned.csv \
    --out examples/iris/outputs/analysis/descriptive.json

python scripts/stats_inferential.py --clean examples/iris/outputs/cleaned/cleaned.csv \
    --out examples/iris/outputs/analysis/inferential.json
```

注意后两步**不传 `--raw`**：它们通过 `dm_types.load_cleaned()` 按 `cleaning_run.json` 里的
`dtype_manifest` 重放类型，而不是再猜一次。若手工把 `cleaned.csv` 单独拿出来、没有
`cleaning_run.json`，脚本会标注 `dtype_source: guess` 并附 warning。

## 结果（已核对）

**清理**：10 项自动动作 / 4 项 never-automatic。`height_m` 因带前导零而 hold；
缺失的两列因 impute 会改变分布而仅标记。字节级可复现，untouched 审计通过。

**校验**：6 项 check 全部 PASS，`verdict: PASS`。

**描述统计**：识别出 5 个数字列。

**推断统计**：同时走通两条分支 ——

- **one-way ANOVA**（等方差）
- **Welch ANOVA**（不等斳差）

两条分支都会记录被拒绝的候选方法及原因（`rejected_alternatives`）、
原始 p 值与校正后 p 值（`p_raw` / `p_adjusted`）、以及带 95% 区间的效应量。
每个比较都带 `rule_source`。

## 为什么这个回归有意义

`tests/test_pipeline_invariants.py` 从这份 `inferential.json` 里取证据，断言两件事：

1. omega² 不会超过 eta²，且与自己的公式一致
   （更正前的实现把它算成 `(MS_b - MS_w)/(MS_b + MS_w)`，那是均值平方之比，不是效应量）
2. 每个比较都记录了被拒绝的候选方法与原因

还有两项不依赖这份文件、而是直接在测试里构造合成数据：

- **正态性不否决参数检验**（n≥30）。n=200 的强偏斜样本仍然走参数检验；n=12 才转秩检验。
- **方差不等走 Welch**，而不是放弃检验。方差比 25 时进 Welch，方差相等时保留合并方差版本。
