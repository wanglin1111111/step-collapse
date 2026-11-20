# step-collapse

步数塌缩方法论技能：把"多步迭代"当可调成本项而非质量保险——多步生成不是"画得慢"，而是在分布建模粒度上欠债；粒度可调且对齐到位，债一次还清，步数塌缩成一步。

一句话：**别只记住"四步变一步"，记住"债是可以一次性还清的"——先问你的流程里，哪几个迭代步骤是在补同一个缺陷。**

## 论文底座（MGFlow / 一步生图）

- 统一框架：FD-Loss（单高斯+W2）与 Drifting（核+KL）= 同一"分布模型+差异度量"框架的不同选择
- 高斯混合：K 个组件（1/4/16 并行），粗粒度全局约束 + 细粒度局部约束同时生效
- 模式崩溃解法：LP 质量约束（猫占 5% 就锁 5%）+ 配对组件更新（第 k 个只对齐第 k 个）
- 实验：ImageNet 256² 提升 23%/38%；FLUX.2 4B 后训练一步化，GenEval/PickScore 优于原四步
- 工程：固定归一化参照（防"生成越烂权重越低"的自我开脱）
- 产业：清华刘淼团队 + DeepSeek；DeepSeek 多模态补人中（借新债）

## 解决什么

| 痛点 | 本技能的做法 |
|---|---|
| 多步迭代当固定配置，不敢砍 | 步数当可调成本项：步数 vs 延迟 vs 质量对照表，数据说话 |
| 不诊断就砍/不砍 | 每步标注"在补哪个缺陷"，同缺陷重复还债才合并 |
| 两派方案各走极端（全局 vs 个体/规则 vs 模型） | 通用三步：unify → 造中间粒度 → 硬性约束锁分配 |
| 堆组件/加参数治模式坍塌 | 表达力 + 硬约束缺一不可，只有前者迟早复发（分数失明） |
| 从头训新模型 | 后训练改造队列：已有模型微调即可一步化，不重训底座 |
| 聚合指标看不出"某类消失" | 类别配额覆盖率探针（廉价，每次评测顺手统计） |
| 归一化跟着输出变 = 自我开脱 | 固定外部参照，缺陷必须暴露 |

## 安装

复制本目录到 `~/.agents/skills/`（或你的 Skill 加载路径）即可。

## 自检

```bash
python scripts/validate.py tests/sample_good.json   # 必须 exit 0
python scripts/validate.py tests/sample_bad.json    # 必须 exit 1

# 一行自验（正反向 + 退出码全覆盖，零依赖）
python tests/test_validate.py
```

## 结构

```
SKILL.md                              工作流入口（一条主线 + 6 步流程 + 7 条硬规则）
references/mgflow-mechanism.md        MGFlow 机制全解（统一框架/K组件/LP约束/固定归一化）+ 实验数据 + 通用三步映射
references/pipeline-playbook.md       出图管线改造实操（对照表模板/后训练队列/三场景/配额探针设计）
references/unify-granularity-constraint.md  通用三步泛化判例（推荐/风控/评测/CI）+ 适用边界 + 失败信号
references/gotchas.md                 分数失明/自我开脱归一化/堆组件治标/从头训诱惑等 9 个坑位
scripts/validate.py                   管线改造计划七维校验器（exit 0/1/2）
tests/sample_good.json                通过基准
tests/sample_bad.json                 拦截基准(缺诊断/未合并/缺unify/写死折中/缺约束/重训无理由/无配额探针)
docs/methodology.md                   方法论全文（奥卡姆剃刀提炼 + 6 条核心 + 5 步行动指南）
```
