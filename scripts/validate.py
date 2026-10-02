#!/usr/bin/env python3
"""validate.py — step-collapse 管线改造计划七维校验器

输入: 管线改造计划 JSON（schema 见 tests/sample_good.json）
  {
    "diagnosis": {
      "steps": [
        {
          "id": "STEP-1",
          "name": "多步迭代第1步",
          "defect": "全局粗结构",          // 该步骤在补哪个缺陷（必填非空）
          "foldable_with": ["STEP-2"]      // 与哪些步骤补同一缺陷（同缺陷重复还债）
        }
      ]
    },
    "unify": {
      "framework": "统一框架描述",          // 两派方案收进的同一模板
      "pairs": [                            // 被统一的两派
        {"name": "单高斯+W2", "role": "coarse"},
        {"name": "核密度+KL", "role": "fine"}
      ]
    },
    "granularity": {
      "param": "K",                          // 粒度参数名
      "levels": [1, 4, 16],                  // 可调节档位（≥2 档）
      "tunable": true,                       // 粒度是否可调（false = 写死折中版）
      "multi_level_benchmark": true          // 是否多档位并行跑对照
    },
    "constraints": {
      "quota_lock": true,                    // 配额锁定（LP 质量约束）
      "paired_update": true,                 // 配对更新（第k个只对齐第k个）
      "hard_not_regex": true                 // 是硬约束不是正则化鼓励
    },
    "rollout": {
      "benchmark_table": true,               // 步数vs延迟vs质量对照表
      "post_train_first": true,              // 后训练改造优先
      "retrain_reason": "",                  // 从头训的理由（post_train_first=false 时必填）
      "target_scenarios": ["low_latency"]    // low_latency | edge_deploy | bulk_render（≥1）
    },
    "evaluation": {
      "aggregate_metrics": ["FID"],          // 聚合指标（可空但须配配额探针）
      "category_quota_coverage": true,       // 类别配额覆盖率探针
      "quota_tolerance": 0.02,               // 配额容差（±pp）
      "fixed_normalizer": true               // 归一化用外部固定参照（非当前输出）
    }
  }

七维校验（任一 FAIL → exit 1）：
  D1 诊断留痕: 每个 step 的 defect 非空（先诊断后砍步）；
     任一 step 的 foldable_with 非空时，对应步骤组必须存在（引用合法）
  D2 同缺陷必塌缩: foldable_with 声明的每个步骤组（≥2 步补同一缺陷）
     必须在 steps 里被标记为合并目标——用 steps 的 "merged_into" 字段声明；
     未声明合并 = 重复还债，白烧算力
  D3 unify 纪律: unify.framework 非空且 pairs ≥2 且 role 含 coarse+fine
     （两派不同构强套 = 双输）
  D4 粒度可调: granularity.tunable=true 且 levels ≥2 档且
     multi_level_benchmark=true（写死折中版/单档 = 没造中间档位）
  D5 约束锁分配: constraints 三项全 true（配额锁定+配对更新+硬约束）；
     缺任一 = 模式坍塌迟早复发（分数失明）
  D6 后训练优先: post_train_first=true；若为 false 则 retrain_reason 非空
     （有后训练接口却重训 = 白走训练周期）
  D7 评测探针: category_quota_coverage=true 且 quota_tolerance ∈ (0,0.2]
     且 fixed_normalizer=true（无配额探针 = 分数失明不可见；
     自适应归一化 = 自我开脱）

退出码：0=通过 / 1=有缺陷 / 2=文件/格式错误
"""
import json
import sys

SCENARIOS = {"low_latency", "edge_deploy", "bulk_render"}
ROLES = {"coarse", "fine"}


def fail(checks, code, msg):
    checks.append(("FAIL", code, msg))


def ok(checks, code, msg):
    checks.append(("OK", code, msg))


def validate(plan):
    checks = []
    steps = (plan.get("diagnosis") or {}).get("steps") or []
    if not steps:
        fail(checks, "D0", "diagnosis.steps 必须是非空数组")
        return checks

    # D1 诊断留痕
    missing_defect = [s.get("id", f"#{i}") for i, s in enumerate(steps)
                      if not str(s.get("defect") or "").strip()]
    if missing_defect:
        fail(checks, "D1", f"步骤未标注补哪个缺陷: {missing_defect}——先诊断后砍步")
    else:
        ok(checks, "D1", f"{len(steps)} 个步骤全部标注缺陷")
    ids = {s.get("id") for s in steps}
    bad_refs = []
    for s in steps:
        for ref in (s.get("foldable_with") or []):
            if ref not in ids:
                bad_refs.append(f"{s.get('id')}→{ref}")
    if bad_refs:
        fail(checks, "D1", f"foldable_with 引用不存在的步骤: {bad_refs}")

    # D2 同缺陷必塌缩（foldable_with 声明的步骤组须 merged_into）
    folded = set()
    for s in steps:
        for ref in (s.get("foldable_with") or []):
            folded.add((s.get("id"), ref))
            folded.add((ref, s.get("id")))
    merged = {s.get("id"): set(s.get("merged_into") or []) for s in steps}
    not_merged = []
    seen = set()
    for s in steps:
        for ref in (s.get("foldable_with") or []):
            if ref not in ids:
                continue
            pair = tuple(sorted((s.get("id"), ref)))
            if pair in seen:
                continue
            seen.add(pair)
            if ref not in merged.get(s.get("id"), set()) and s.get("id") not in merged.get(ref, set()):
                not_merged.append(f"{s.get('id')}↔{ref}")
    if not_merged:
        fail(checks, "D2", f"同缺陷重复还债未声明合并: {not_merged}——必须塌缩，白烧算力")
    else:
        ok(checks, "D2", "同缺陷步骤组均已声明合并")

    # D3 unify 纪律
    uf = plan.get("unify") or {}
    pairs = uf.get("pairs") or []
    roles = {p.get("role") for p in pairs}
    if not str(uf.get("framework") or "").strip():
        fail(checks, "D3", "unify.framework 缺失——两派没收进同一张图纸")
    elif len(pairs) < 2 or not ({"coarse", "fine"} <= roles):
        fail(checks, "D3", f"unify.pairs 须 ≥2 派且含 coarse+fine: {roles}")
    else:
        ok(checks, "D3", f"统一框架成立（{len(pairs)} 派: {sorted(roles)}）")

    # D4 粒度可调
    gr = plan.get("granularity") or {}
    levels = gr.get("levels") or []
    if gr.get("tunable") is not True:
        fail(checks, "D4", "granularity.tunable=false——写死折中版=没造中间档位")
    elif len(levels) < 2:
        fail(checks, "D4", f"levels={levels} 不足 2 档——粒度必须可调节")
    elif gr.get("multi_level_benchmark") is not True:
        fail(checks, "D4", "multi_level_benchmark=false——多档位须并行跑对照让数据选档")
    else:
        ok(checks, "D4", f"粒度可调（参数 {gr.get('param')}，档位 {levels}，多档对照）")

    # D5 约束锁分配
    cs = plan.get("constraints") or {}
    missing_cs = [k for k in ("quota_lock", "paired_update", "hard_not_regex") if cs.get(k) is not True]
    if missing_cs:
        fail(checks, "D5", f"硬性约束缺: {missing_cs}——只有表达力没有约束=模式坍塌迟早复发")
    else:
        ok(checks, "D5", "约束齐全（配额锁定+配对更新+硬约束）")

    # D6 后训练优先
    rl = plan.get("rollout") or {}
    if rl.get("post_train_first") is True:
        ok(checks, "D6", "后训练改造优先")
    elif rl.get("post_train_first") is False:
        if not str(rl.get("retrain_reason") or "").strip():
            fail(checks, "D6", "post_train_first=false 但 retrain_reason 缺失——有后训练接口却重训须写明理由")
        else:
            ok(checks, "D6", "重训已留痕理由")
    else:
        fail(checks, "D6", "rollout.post_train_first 未声明（true=后训练优先 / false=重训须理由）")

    # D7 评测探针
    ev = plan.get("evaluation") or {}
    q = ev.get("quota_tolerance")
    if ev.get("category_quota_coverage") is not True:
        fail(checks, "D7", "category_quota_coverage=false——无类别配额探针，分数失明不可见")
    elif not isinstance(q, (int, float)) or not (0 < q <= 0.2):
        fail(checks, "D7", f"quota_tolerance={q!r} 非法——须在 (0, 0.2]（±pp）")
    elif ev.get("fixed_normalizer") is not True:
        fail(checks, "D7", "fixed_normalizer=false——归一化跟当前输出走=自我开脱，须外部固定参照")
    else:
        ok(checks, "D7", f"评测探针齐全（配额容差 ±{q}，固定归一化）")

    return checks


def main():
    if len(sys.argv) != 2:
        print("usage: python validate.py plan.json", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取/解析: {e}", file=sys.stderr)
        return 2
    if not isinstance(plan, dict):
        print("ERROR: 顶层必须是 JSON 对象", file=sys.stderr)
        return 2

    checks = validate(plan)
    fails = [c for c in checks if c[0] == "FAIL"]
    for status, code, msg in checks:
        if status == "FAIL":
            print(f"[{code}] FAIL {msg}")
    print(f"== {len(checks) - len(fails)} OK / {len(fails)} FAIL ==")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
