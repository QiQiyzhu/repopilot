# 93 tests passed. Why reject the change?

**两个补测方案，现有验证器都给绿灯；只有一个完成了任务。** RepoPilot 现在提供一个可以实际重跑的反例，用来解释“执行成功”与“任务完成”之间缺少的证据。

[实际结果 JSON](../evaluation/results/decision-case.json) · [复现入口](../backend/repopilot/decision_case.py) · [面试讲解](interview-deep-dive.md)

## 先做判断，再看结果

任务是为 ARC//SHIFT 的 `distance` 增加一项回归测试，保护欧氏距离行为；实现保持不变。目标固定为提交 `b17f4c24cf95a02d3197ec493026b6f23c8f2c3e`，复用原有 36 项契约中的 `arc-017-test-distance` 及其已有 mutation。

候选 A 检查水平移动和同一点：

```ts
assert.equal(distance({x:0,y:0}, {x:3,y:0}), 3);
assert.equal(distance({x:2,y:2}, {x:2,y:2}), 0);
```

候选 B 检查斜向移动：

```ts
assert.equal(distance({x:0,y:0}, {x:3,y:4}), 5);
```

两个候选都让完整回归达到 **93 passed**，都修改了要求的测试文件，都通过原有 `add-unit-test` Skill 与 `EvidenceVerifier`。如果任务要求的是“有效保护距离语义”，你会同时接受它们吗？

## 实际对照

| 证据 | A：仅水平／同点 | B：3–4–5 斜向参考 |
|---|---|---|
| 正确基线上的完整回归 | 93 passed | 93 passed |
| 原有 in-loop verifier | passed | passed |
| 只有要求的测试文件改变 | 是 | 是 |
| 独立执行新测试，正确实现 | exit 0，1 个 test body 执行 | exit 0，1 个 test body 执行 |
| 临时换成已知错误实现，再只执行新测试 | exit 0，错误未被发现 | exit 1，`7 !== 5` |
| 任务最终验收 | **拒绝：未识别指定回归** | **接受：识别此指定回归** |
| 原实现恢复及 SHA256 核对 | 通过 | 通过 |

错误实现来自既有数据集：把 `Math.hypot(dx, dy)` 换为 `Math.abs(dx) + Math.abs(dy)`。水平移动时两者都是 3；斜向 `(3,4)` 时分别是 5 与 7。A 的断言不是空断言，却没有区分任务关心的两种行为；B 的断言数量更少，辨别力更强。

这里**没有证明基线游戏存在这个错误**。mutation 是明确标记的临时评估控制。A 与 B 也是 AI-assisted 编写的实验候选，**不是观测到某个 LLM 欺骗测试的记录**；此实验没有调用真实模型或 FakeModelProvider。所有通过／失败结果来自实际进程。

## 工程判断

`EvidenceVerifier` 没有“算错”：它准确检查了配置给它的命令、diff 和目标文件。问题是这些检查不足以证明新增测试能挡住未来回归。把其 `passed` 展开为“这份配置下的检查通过”，再让独立评估决定特定任务是否完成，比把所有绿灯都叫成功更诚实。

这个案例复用现有组件：`GitWorkspace` 只归档固定提交；`ToolRouter` 应用候选并运行完整回归；`EvidenceVerifier` 给出命令和文件证据；外部 `evaluation/acceptance.cjs` 执行密封的任务契约。案例没有扩展 Agent 的命令权限，也没有修改游戏源码。

mutation 阶段**只执行新补的测试**：完整回归里的旧测试可能已经能发现错误，不能把旧测试的保护能力算成新测试的贡献。完整回归仍在正确基线上执行，负责另一件事——检查新补测试没有破坏已有行为。

分析时还修复了一个实际评估边界：此前 `not passed` 会把超时也记成成功识别 mutation。现在共享的 `contract_rejected` 要求明确的 evaluator exit 1，超时和信号退出不能当作负控制成功。案例额外要求出现本例预期的 `7 !== 5`；真实子进程超时回归保护了这个区分。exit 1 本身仍不是通用正确性证明，本例依赖正确基线、已知 mutation 与具体断言三者一起成立。

## 没有采用的方案

| 方案 | 为什么没有采用 |
|---|---|
| 只看测试总数和绿色徽标 | A 的断言更多，93 项也全绿，仍未满足补测目的 |
| 再让一个 LLM 判断“是否完成” | 可以辅助解释，却不能替代这条可执行的区分证据；本例无需付费模型 |
| 在 mutant 上运行全部旧测试并宣称新测试充分 | 会把已有回归能力误算到候选补测上 |
| 把任意失败都视为抓到了错误 | 超时、环境故障与预期断言失败不是同一种证据 |
| 为展示增加任意 shell 或远程执行能力 | 扩大安全范围，与回答这个问题无关 |

## 本机复现

先完成 README 的 Python 环境安装，再运行以下命令。ARC 路径只用于读取固定提交；实验会新建自己的归档 workspace。

```sh
git clone https://github.com/QiQiyzhu/arc-shift.git ../arc-shift
npm ci --prefix evaluation --ignore-scripts
python -m repopilot.decision_case ../arc-shift --trust-code --output outputs/decision-case.json
```

Windows 可显式把临时工作区与 npm 缓存放在空间充足的盘，例如 `--data D:/RepoPilot-experiments`。安装依赖时不运行 install scripts；`--trust-code` 明确允许执行这个固定版本的测试。候选 TypeScript 与测试仍在宿主进程执行，**不是敌对代码的 OS 沙箱**。无 API Key、模型或联网业务写操作。

程序只有在 A 被外部拒绝、B 被接受、两者完整回归通过、目标文件范围正确、实现恢复成功时才 exit 0。输出包含每一步 exit code、耗时、候选源码、diff、源文件 hash 与适用边界。仓库源码／workspace 的本机绝对路径会被占位符替换，断言与数值不变。每次运行创建新目录；原始游戏 checkout 不改变。

CI 执行相同命令，并把每次结果上传到 `harness-evidence` artifact。检查报告内的受测 SHA 与 source hash；不能把一次本机结果假称为所有平台上的通用结果。

## 下一项有价值的实验

当前只覆盖一项公开已知任务与一个 mutation，不能报告“Agent 准确率提升”。下一步应预先固定一组未向候选作者公开的几何等价类与错误实现，分别记录候选的全量回归通过、独立契约通过、mutation 检出和基础设施错误。先验证评估器本身能区分正负控制，再在明确授权后尝试真实模型；不要看到候选结果后修改题目来提高分数。
