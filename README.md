# 拾光 · Lumen

> 本地优先的 AI 成长搭子 —— 不只是问答，而是**记得你、理解你、敢挑战你的学习伙伴**。

**北极星（v2.0）**：让你**愿意回来**，回来时**一起学**——它是成长搭子（learning companion），不是学习工具（learning tool）。

拾光是一个 **Agentic 架构的本地 AI 应用**：FastAPI 后端 + Pydantic AI 多 Agent + React 前端，融合 RAG 记忆检索、多视角研讨、多模态理解、自建评测体系。所有个人数据本地存储，不上传。

---

## 核心特色（为什么它不是又一个聊天机器人）

### 1. 记忆系统 —— 真正"记得你"（三层记忆 + 向量检索）
- **工作记忆/状态轮**：每轮注入当前状态（情绪/卡点/节奏/意愿），注入内容标注"疑似"边界，数据给觉察不给判断
- **长期记忆**：9 字段结构化条目（日期/来源/重要度/类别/内容），四原语治理（ADD/UPDATE/DELETE/NOOP）
- **向量检索（JIT）**：bge-m3 嵌入 + ChromaDB + 三因子排序（相关性 0.7 + 重要度 0.15 + 新鲜度 0.15），实验验证最优权重
- **人可审计**：记忆文件 git 跟踪，可回滚可导出——记忆不是黑盒

### 2. 先贤会议 —— 多视角深度研讨（Multi-Agent Debate）
- 星宿（sage）多角色研讨：笛卡尔理性演绎 × 培根经验归纳（deep 模式）等多组合
- **RAPTOR 树**：把原书递归聚类摘要成层级树，星宿发言时**自主检索树作为"书中证据"**（工具化调用，实测调用率 100%）
- 会议引擎：SSE 流式、停止四层参数、分歧聚焦、报告进记忆

### 3. 多模态理解 —— 拍照问错题
- **GLM-4.6V-Flash**（免费视觉模型，128K 上下文）识图：图表趋势、几何题、错题、笔记
- 与本地 OCR（RapidOCR）互补：OCR 读字 / 视觉理解看图，双模型降级链
- 对话中自动触发：上传图片 → 拾光自主调视觉工具 + 结合记忆回答

### 4. Agentic Search —— 多 Agent 并行研究
- `deleg_study`：主 Agent 拆解目标 → 2-5 个子 Agent **并行**搜索研究（asyncio.gather，单失败不中断）
- 双搜索源路由：Tavily（国际源）+ 博查（中文源，DeepSeek 官方同款引擎），按任务语义选源
- 按需触发：闲聊/通用知识零搜索，需要最新信息才搜（实测验证克制性）

### 5. 成长搭子 —— 挑战与接住
- 行为原则（罗盘写法）：可以质疑/反驳你，对事不对人，分寸判断权在模型
- 数据给觉察不给判断：状态轮是觉察不是指令，不替模型做判断

### 6. 自建评测体系 —— 不是"已验证"，是"可验证"
- LLM 模拟用户（3 类 persona）+ 场景集（复习/压力面试/长马拉松），定位**智能模糊测试**（发现系统怎么坏）
- 实测产出：**160 轮马拉松 0 字塌方**（修复前 66 轮起塌方）；画像层串扰实证；行为漂移治理

---

## 技术架构

```
frontend/  React + TS + Vite + Tailwind（三栏：学习路径 | 聊天 | 记忆/星阁）
   ↓ /api（SSE 流式）
app/
  main.py         FastAPI 入口：SSE 对话流 / 通知 / 上传 / 会议 / 蒸馏 API
  agent/tutor.py  拾光大脑：MINIMAL_PROMPT + 静态行为前缀 + 画像/状态注入
  agent/delegation.py  多 Agent 并行研究（子 Agent 只读工具白名单）
  agent/model.py  LLM 层：主/备模型 fallback 链 + 熔断 + 成本台账
  council/        先贤会议：引擎 / 星宿 Agent / RAPTOR 树 / 蒸馏管线 / 模式预设
  memory/         记忆层：schema（9 字段）/ store（四原语）/ vector（bge-m3+ChromaDB）
  prompts/        Prompt 外置（YAML 可审计，代码不写死）
  tools/          工具集：web_search(Tavily) / bocha_search(博查) / vision(GLM-4.6V) / OCR /
                  sandbox / documents / kb(LlamaIndex) / scheduler
  routers/        REST API 路由
  scheduler.py    督促调度器（到期唤醒 → 独立 Agent 生成提醒）
scripts/          评测设施（模拟用户 / 回归套件 / 验证脚本）
```

### 工程实践
- **Prompt 即数据**：行为前缀外置 YAML，字节稳定注入（Context Caching 友好）
- **判断无墙，不变量无口**：语义判断归模型（罗盘），确定性不变量锁代码（格式/ID/护栏）
- **容错链**：主→备模型 fallback、120s 硬超时、熔断、单点失败降级不中断
- **可观测性**：成本台账（token_usage）、injection_log、会议工具调用率统计、失败日志落盘
- **看门狗**：双服务自愈（uvicorn + Ollama），单例锁防多代残留

---

## 快速开始

### 依赖
- Python 3.12+、Node.js 18+
- **Ollama**（本地 embedding 服务）：https://ollama.com 下载 → `ollama pull bge-m3`
  （或 ModelScope 下 bge-m3 GGUF 导入；`OLLAMA_MODELS` 可指定模型盘符）

### 启动
```bat
:: ① 配置
copy .env.example .env   :: 填 DEEPSEEK_API_KEY（必填）；TAVILY/BOCHA/ZHIPU（可选增强）
cd frontend && npm install && cd ..

:: ② 一键启动（自动 build 前端 + 拉起 Ollama + 后端 + 看门狗）
双击 start.bat

:: ③ 浏览器打开 http://127.0.0.1:8000
```

### 环境变量（.env）
| 变量 | 必填 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | 主模型（deepseek-v4-flash） |
| `TAVILY_API_KEY` | | 联网搜索-国际源（免费 1000/月） |
| `BOCHA_API_KEY` | | 联网搜索-中文源（免费 2000 次） |
| `ZHIPU_API_KEY` | | 识图（GLM-4.6V-Flash 免费） |
| `SHIGUANG_TOKEN` | | 鉴权（局域网/公网必配） |
| `FALLBACK_*` | | 备用模型（fallback 链） |

---

## 项目结构

```
app/            后端（FastAPI + Agent + 记忆 + 会议 + 工具）
frontend/       前端（React + TS + Vite）
scripts/        评测设施与工具脚本
scenarios/      评测场景集
memory/         用户记忆（运行时生成，git 忽略——隐私）
data/           运行时数据（SQLite/向量/上传，git 忽略——隐私）
```

**隐私承诺**：`.env`（密钥）、`memory/`（个人记忆）、`data/`（运行时数据）全部 git 忽略，绝不上传。所有数据本地存储。

---

## License

MIT
