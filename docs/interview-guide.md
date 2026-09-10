# 面试前读懂 RepoPilot

## 30 秒介绍

RepoPilot 是一个围绕代码修改任务的 Agent harness。模型输出结构化 action，运行时负责隔离 checkout、工具权限、上下文预算、状态流转和真实验证。我用已有 ARC//SHIFT 的固定版本构造了 36 个有正负对照的任务，并把已运行的 harness 验证与尚未运行的真实模型 benchmark 分开报告。

## 三分钟演示

1. 启动本地前后端，点击 Run MCP demo。明确说明这是 deterministic fixture，没有模型推理。
2. 展开失败的 pytest 事件：这里的失败是被成功复现的 bug，不是被藏掉的错误。
3. 展开 apply_patch 和后续 pytest，说明 native 与实际 MCP stdio 的区别。
4. 切换 Diff、Verification、Context，看真实文件差异、退出码、选择和丢弃的 context。
5. 打开 Memory，查看 task / trace provenance 并 invalidate 一条记录。
6. 打开 Evaluation：36/36 是 acceptance 合同有效性，五组是 harness wiring；真实模型性能仍未测量。

## 十个必须读懂的核心文件

| 文件 | 必须能解释的问题 |
|---|---|
| `backend/repopilot/models.py` | 什么是任务状态、Action、预算与证据契约？ |
| `backend/repopilot/harness.py` | 谁决定完成？REPAIR 如何受限？取消如何传播？ |
| `backend/repopilot/security.py` | 路径和命令为什么只能算应用边界，不能称强 sandbox？ |
| `backend/repopilot/workspace.py` | 为什么从 committed archive 开始，不碰用户工作树？ |
| `backend/repopilot/tools.py` | patch 如何唯一匹配？新文件如何进入 diff？删除如何审批？ |
| `backend/repopilot/providers.py` | 如何替换 provider？Fake 与 Replay 为什么不能当模型分数？ |
| `backend/repopilot/mcp_client.py` | initialize、call_tool、stdio process lifetime 如何工作？ |
| `backend/repopilot/context.py` | naive 与结构化词法检索有什么差别？预算如何估计？ |
| `backend/repopilot/verifier.py` | 单元测试、类型检查、文件契约如何共同决定通过？ |
| `backend/repopilot/evaluation.py` | 正负对照与消融实验的公平性和局限是什么？ |

补充阅读 `store.py` 的 parameterized SQL / WAL、`api.py` 的 SSE cursor / disconnect、`skills.py` 的权限声明以及 `frontend/src/App.tsx` 的任务观察生命周期。

## 五条可使用的简历表述

- 基于 Python 3.12、FastAPI、React 和 SQLite 实现代码任务执行平台，具备七态 harness、限次 repair、取消/超时、真实 diff 与可重放 SSE trace。
- 实现原生工具与真实 MCP stdio server/client 两种传输，使用独立 Git snapshot、路径限制、命令 allowlist、输出上限和人工删除审批控制执行边界。
- 为 ARC//SHIFT 固定提交设计并验证 36 项独立任务的正负对照，覆盖 bug 修复、补测试、小功能、重构、性能契约和文档代码一致性；6 项补测试任务进一步通过 mutation adequacy 检查。
- 实现带预算与可视化 provenance 的上下文检索、严格版本隔离的 memory，以及五组可切换 harness 配置；真实执行已知 fixture 的五组对照并如实报告其不能代表 LLM 能力提升。
- 建立无付费 API 依赖的自动化验证流程，覆盖后端生命周期/安全/API/MCP、前端请求边界和真实浏览器交互，并提供 Docker Compose 与 CI 构建配置。

这些表述不包含虚构的生产用户、模型训练、百分比性能提升或真实 LLM 解题率。请不要把“production-oriented”改成“已大规模生产使用”。

## 常见追问

**为何不是一个 while loop？** while 只是EXECUTE内部的调度器，状态转换表、permission gate、budget、verifier 和持久化事件决定整个生命周期。

**为何不用 LangChain / Redis / Kubernetes？** 当前需要的是可读的执行边界和可重复证据；单进程 SQLite 已能表达项目问题。可以指出协议接口，而不是为假想规模增加基础设施。

**MCP 带来什么？** 工具发现和跨进程标准化。Function calling 是模型动作选择契约；Skill 是权限和流程策略；三者不是互相替代的名字。

**你证明模型更强了吗？** 没有。证明的是任务合同、工具传输、验证与记忆开关可运行。真实 provider 实验需要实际授权调用，当前结果明确为未运行。

**你最有价值的调试是什么？** MCP里子进程继承了协议stdin，实际pytest阻塞；设置DEVNULL后相同真实stdio用例通过。另一个是git diff默认遗漏untracked新文件，因此专门补齐新文件diff并验证。

**如何上线给外部用户？** 当前API只用于本地可信仓库。需要每任务强隔离、认证/授权、多租户ownership、网络/secret broker、可靠队列和成本预留，再谈公开运行。

**AI 辅助开发责任？** 本项目由 AI 辅助实现。提交者负责理解模块、复现命令、检查边界和解释未覆盖情况。面试应主动讲出一个真实失败和一个取舍。
