# 拾光 · Lumen

> 你的 AI 学习搭子——记得你学到哪、怎么学最快、上次卡在哪。北极星：**学任何新东西时第一个打开的窗口是它**。

## 它是什么

一个本地运行的 AI 学习搭档（DeepSeek v4-flash + Pydantic AI），核心不是"问答"，而是**记得你、督促你、越用越懂你**：

- **对话**：SSE 流式，逐字回答，思考过程可折叠查看
- **记忆**：你说过的偏好/目标/卡点自动沉淀，可向量检索、可在界面修正/删除（git 跟踪人可审）
- **工具**：Python 沙箱 / OCR 看图 / 读文档(PDF/Word) / 联网搜索 / 个人知识库——大脑自主调度
- **督促**：说"明天 9 点提醒我复习 X"，它自己安排时间，到点弹提醒（浏览器通知+页内横幅）
- **多 agent**：说"帮我系统学 Python"，它拆成独立子任务并行研究，进度卡实时点亮
- **进化**：讲得不好会反思入库、讲得好会沉淀技能——同类问题下次直接复用更好的讲法

## 快速开始

```bat
:: ① 准备环境
::   - Python 3.13 + 前端依赖：cd frontend && npm install
::   - 复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY（必填）
:: ② 一键启动（自动 build 前端 + 起后端 + 看门狗）
双击 start.bat
:: ③ 浏览器打开 http://127.0.0.1:5173
```

- **环境变量**（`.env`）：
  - 必填：`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`
  - 可选：`TAVILY_API_KEY`（联网搜索）、`SHIGUANG_TOKEN`（鉴权，局域网/公网访问必配）、`FALLBACK_*`（备用模型）
  - 环境变量（非 .env）：`DATA_DIR`（数据根目录，评测隔离用）、`EXPERIMENT_MODE=1`（实验模式，拦截提醒投递）
- 手机访问：同 Wi-Fi 打开 `http://<电脑局域网IP>:5173`（vite 已监听 0.0.0.0）

## 架构

```
frontend/  React+TS+Vite+Tailwind 三栏：学习路径 | 聊天 | 记忆
   ↓  /api（vite proxy → 8000）
app/
  main.py         FastAPI + SSE 流式 + 通知/任务/反馈 API
  agent/tutor.py  拾光大脑（instructions 每轮注入画像+时刻+反思）
  agent/delegation.py  M7 多 agent（deleg_study 并行研究 + 进度上报）
  agent/evolution.py   M8 进化层（反思/技能库/检索）
  memory/         M2 三层记忆（schema/store/vector：bge-m3+chromadb）
  db/             sessions + wakeups（督促闭环）
  tools/          M3 工具五件套（web_search/sandbox/ocr/documents/kb）
  scheduler.py    M6 调度器（每分钟扫到期唤醒 → 独立 agent 生成提醒）
memory/           人可审的记忆文件（git 跟踪）：user_memory / profile / reflections / skills
data/             SQLite + chromadb 向量（会话/唤醒/知识库）
data-experiment/  实验隔离库（DATA_DIR 环境变量指向，主库零接触）
scripts/          模拟用户评测设施：sim_runner / sim_reporter / verify_all / isolation_check
scenarios/        评测场景集（复习/压力面试/长马拉松）
```

## 模拟用户评测设施（v0.2）

自建 LLM 模拟用户自动化评测体系——定位是**智能模糊测试**（发现系统怎么坏），不是用户预测器：

- **3 类典型学习者 persona**（备考冲刺/碎片学习/深度钻研）+ 行为采样器（按真实分布掷骰，非 LLM 默认行为）+ 场景集（复习/压力面试/长马拉松）
- **三层验证结构**：① AI 模拟抓边界（坏没坏）② 开发者真实使用判价值（dogfooding）③ 长期真实用户判留存——每层不互相替代
- **主要产出**：3 种子 × 160 轮马拉松 0 字塌方（修复前 166 轮实测 66 轮起 60/100 轮 0 字）；画像层串扰实证（单用户架构固有，2.0 多用户预研输入）；识别并治理了模拟用户自身的长会话行为漂移
- **实验隔离**：`DATA_DIR=data-experiment` 启动独立实验实例（端口 9000），主库零接触；`EXPERIMENT_MODE=1` 拦截提醒投递

**用法**（需先启动本地服务 + 配置 .env）：
```bash
# 实验实例（隔离库，主库零接触）
DATA_DIR=data-experiment EXPERIMENT_MODE=1 uvicorn app.main:app --port 9000

# 跑一个 persona × 场景（如备考冲刺 × 压力面试）
python scripts/sim_runner.py --persona exam_crammer --scenario 002 --seeds 3

# 采样器自洽回归（改权重后的哨兵）
python scripts/behavior_sampler_check.py

# 隔离验收（实验后主库零污染验证）
python scripts/isolation_check.py
```

## 设计原则（GOALS.md 全文为纲）

- **判断无墙，不变量无口**：语义判断（该不该提醒/记不记/怎么教）归模型——不设墙；确定性不变量（去重阈值/频控/沙箱上限）锁代码——不开口。从"规则堆砌致 agent 死板"的失败版迭代而来（2026-08-12）
- **引导在 prompt、护栏在数据、约束零记录**：importance 模型打、画像模型写、去重阈值是护栏（中间带交模型复核）
- **上下文工程**：每轮只注入画像摘要+行为指引+最近反思（≤2000 token），细节走 JIT 检索；长会话 compaction（90K 阈值 + 尾部 20K 保留 + 幂等摘要）
- **借力不自研**：Pydantic AI / LlamaIndex / bge-m3 / chromadb / Tavily / lucide 等成熟组件，零自研算法
- **调研先行**：每里程碑先吃透官方文档/论文原文归档 research/（APA+[R#]+核查日期），再动手
- **模拟用户 = 智能模糊测试**：LLM 模拟用户只测"系统坏没坏"（抓边界/回归），不测"人会不会回来"（价值层必须真人）——验证有停止准则，不无限加测

## 关键技术栈

DeepSeek v4-flash · Pydantic AI 2.27 · FastAPI · React 19 + Tailwind v4 + zustand · bge-m3 (GPU) · chromadb · LlamaIndex · SQLite

## 边界与已知项

- 本地单机运行，记忆不做云同步；单 uvicorn worker（进度表/调度器进程内）
- 服务被回收时双击 `start.bat` 即可重启（记忆/会话持久化在磁盘，不丢）
- **自愈（#21）**：`scripts/service_guard.py` 看门狗（0.0.0.0 监听 + 崩溃 3s 自动重启 + token 护栏）；开机自启靠启动文件夹
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\shiguang_guard.bat`（schtasks/vbs 被安全策略禁，启动文件夹是唯一合规路径）。
  **换机器/重装系统后必须重建此文件**，否则自愈静默失效（服务仍可用，只是崩了没人拉起）。
- 督促/教学效果不承诺"学得更快"，只保证"记得你、有方法地帮你"

## 文档与数据

- 设计原则、里程碑与完整工程文档（踩坑实录 / 评测报告 / 简历口径等）位于项目主仓（私有），不在本公开仓库
- 本仓库为代码发布副本：**不含个人记忆数据、会话数据与个人文档**（隐私保护）
