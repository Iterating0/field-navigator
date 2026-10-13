# Field Navigator

面向学生的科研领域探索 MVP：输入领域 → 查找论文 → 提取前置领域与研究分支 → 展示知识地图 → 点击子领域继续探索。论文是领域节点下的证据与学习材料，图中的主要节点始终是领域。

Docker Compose 部署说明见 [DEPLOY.md](DEPLOY.md)；可将文中的部署指令直接交给自动部署器。

魔搭单容器部署见 [ModelScope部署说明](deploy/modelscope.md)。参赛作品范围、演示路径与交付状态见 [参赛说明](docs/HACKATHON.md)。

界面采用搜索、左侧探索记录、中间分支表与关系图、右侧论文详情布局。支持缩放、拖动画布、放大图谱、置信度筛选、前置/分支显示开关、已分析节点的二层视图与 JSON 导出。

## 安装

需要 Python 3.11+、Node.js 22+。本次验证环境：Windows、Python 3.14.3、Node.js 24.14.0。无需数据库服务或用户账户。

在项目根目录运行（PowerShell）：

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
cd frontend
npm ci
cd ..
Copy-Item .env.example .env
```

macOS / Linux 使用 `backend/.venv/bin/python` 替换 Windows 的虚拟环境路径，使用 `cp .env.example .env` 复制配置。`requirements.lock` 和 `package-lock.json` 记录经过验证的依赖；更新 Python 依赖时可用 `requirements.txt` 中的兼容范围。

## 启动

最方便的方式，在根目录运行：

```powershell
python scripts/dev.py
```

打开 [Field Navigator](http://127.0.0.1:5173)。按 `Ctrl+C` 会关闭两个子服务。启动脚本会检查 8000 和 5173 端口占用，不会终止其他进程。服务只监听本机地址。

在 Project Manager 中请选择“浏览器部署”，工作目录设为项目根目录（不是 `frontend`）。启动命令使用带引号的绝对路径，避免工作目录或中文、空格导致找不到文件：

```text
"<项目根目录>\backend\.venv\Scripts\python.exe" "<项目根目录>\scripts\dev.py" --port {port}
```

将两处 `<项目根目录>` 替换为实际路径。首选端口为 `5173`，URL 为 `http://127.0.0.1:{port}/`。脚本会先等后端就绪，再启动前端，并使用启动器分配的端口。不要仅启动 `frontend` 中的 `npm run dev`，它只运行前端。

也可以分别启动：

```powershell
# 终端一：后端
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
# 终端二：前端
cd frontend
npm run dev
```

接口文档：[FastAPI /docs](http://127.0.0.1:8000/docs)。前端的 `/api` 通过 Vite 转发到后端。

## API 配置与模式

所有 key 只在项目根目录 `.env` 中配置，前端不会获取 key，`.env` 已忽略提交。修改配置后重启后端。

```dotenv
OPENALEX_API_KEY=
OPENALEX_MAILTO=
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=
LLM_RESPONSE_FORMAT=auto
LLM_THINKING=auto
LLM_MAX_TOKENS=16384
LLM_ANALYSIS_LIMIT=0
```

- OpenAlex 支持匿名使用，但匿名预算在同一网络 IP 上共享；建议在 [OpenAlex 设置](https://openalex.org/settings/api) 获取 key。实现使用 `Authorization: Bearer`，不会把 key 放进查询 URL。[认证文档](https://help.openalex.org/api/authentication/)
- LLM 使用 OpenAI-compatible Chat Completions HTTP 协议。填写实际服务的 base URL、key 和支持结构化输出的模型名称即可。没有绑定模型 SDK。
- 默认 `LLM_RESPONSE_FORMAT=auto`：先请求严格 `json_schema`，仅在服务明确返回不支持该格式的 HTTP 400/422 时，改用 `json_object` 重试一次，并在当前后端进程中记住该兼容模式。鉴权、限流、模型名称错误及无效 schema 不触发降级。两种模式都通过 Pydantic 校验，拒绝无效结构。
- 可强制设置 `json_schema`（不自动降级）或 `json_object`。DeepSeek Chat Completions 使用 JSON mode，可选择 `auto` 或 `json_object`。修改 `.env` 后重启后端。[DeepSeek JSON 输出文档](https://api-docs.deepseek.com/guides/json_mode/)
- 模型请求独立使用 `LLM_REQUEST_TIMEOUT_SECONDS`（默认 180 秒），避免分析多篇摘要时被论文检索的 `REQUEST_TIMEOUT_SECONDS`（默认 45 秒）提前中止。
- `LLM_THINKING=auto` 对官方 DeepSeek 关闭思考，对其他服务保留原行为。可设 `low` / `high` 使用 DeepSeek 兼容的思考参数，或设 `provider` 完全遵循服务默认值。`LLM_MAX_TOKENS` 包含推理预算；截断结果不会保存。
- `LLM_ANALYSIS_LIMIT=0` 默认分析全部候选。设为 `16` 可试验代表性候选筛选，界面显示实际分析数量与覆盖限制。完整优化设计、实测和对比工具见 [性能说明](docs/HACKATHON.md)。
- 无 `LLM_API_KEY` 时使用 `MockLLMProvider`。预设仅覆盖 NHSE 及其分支；其他领域可以实时搜索论文，但不编造领域关系。

| 界面模式 | 论文来源 | 分析行为 |
| --- | --- | --- |
| 自动 | 优先 OpenAlex；失败时仅对预设 NHSE 领域回退到演示书目 | 有真实论文且配置 LLM 时调用模型，否则明确标注预设拆分 |
| OpenAlex 实时 | 只用 OpenAlex，失败直接显示错误 | 有 key 用 LLM；无 key 用有限的预设拆分 |
| 离线演示 | 内置已核对书目，无网络依赖 | 始终使用预设拆分，即使配置了 LLM key 也不调用模型 |

进入页面自动探索 NHSE。可试：`NHSE` → `Incoherent NHSE` → `Photonic quantum walks`。叶节点会显示无更多分支。点击左侧记录或面包屑返回。

**外部服务验证：** 2026-09-20，OpenAlex 匿名搜索曾返回 429（共享 IP 预算耗尽），当时仅验证了离线演示与模拟 LLM 合约。2026-09-21，使用本机已配置的 OpenAlex + DeepSeek `deepseek-flash`，实际完成 `two dimensional electron gas` 的自动模式分析：40 篇候选、8 篇核心论文、5 个前置领域、7 个研究分支，约 74 秒完成。该验证确认请求、结构校验和缓存流程正常，不代表领域拆分质量已完成人工评测。

## 架构与替换点

```text
frontend/src/components/{SearchBar,FieldGraph,DetailPanel}.tsx
              ↓ POST /api/fields/explore/stream（NDJSON，原 JSON 接口仍保留）
backend/app/api/fields.py
              ↓
services/field_explorer.py        只编排步骤、缓存和回退
  ├── providers/base.py           PaperProvider / LLMProvider 协议
  ├── providers/openalex.py       搜索 / 单篇查询 / 引用查询
  ├── services/field_decomposer.py 提示词、JSON schema、证据 ID 清洗
  │     ├── providers/llm.py      OpenAI-compatible HTTP transport
  │     └── providers/mock.py     有边界的预设演示
  ├── services/paper_ranker.py    独立排序函数和服务
  ├── services/paper_selector.py 可选的代表性候选筛选实验
  └── db/cache.py                SQLite 事务与缓存
```

数据合同在 `backend/app/models/schemas.py` 和 `frontend/src/types/index.ts`。`FieldNode` 包含 summary、prerequisites、subfields、core_papers，并额外返回来源、警告、生成时间和 cache_hit。`FieldRelation.evidence_paper_ids` 标明候选论文证据；`evidence_papers` 返回关系实际引用的候选论文元数据，关系详情可打开原始来源，即使该论文不在核心论文列表中。`CorePaper.signals` 暴露各评分项。

- 替换 OpenAlex：实现 `PaperProvider.search_papers/get_paper/get_citations`，返回 `Paper`，在 `main.py` 注入。
- 替换 LLM：实现 `LLMProvider.generate_structured`，在 `main.py` 注入。
- 改领域拆分：修改 `FieldDecomposer` 的提示词/清洗或替换整个服务，保持 `Decomposition` 合同。
- 改排序：替换 `PaperRanker.rank` 或 `core_paper_score`，保持 `CorePaper` 合同；UI 无须修改。
- 改权重：修改 `.env` 中的 `RANK_*` 即可。

## 当前算法

OpenAlex 搜索默认取相关性排序的前 40 条，排除撤稿记录，重建可用的倒排摘要。单次分析最多发送 40 篇候选、每篇摘要前 2,500 字符与前 8 位作者。论文元数据和领域输入作为不可信数据传给模型，提示词要求忽略其中的指令。

检索完成先显示初筛论文；模型分别并行生成领域地图和论文评价，地图完成即显示，评价完成再给出最终排序。输入使用短论文 ID，输出后恢复真实证据 ID。简介和理由有长度预算，减少等待。领域必须是概念依赖或有实质内容的研究方向；去掉自身、重复、前置/分支交叉重复。真实 LLM 关系必须引用至少一个候选论文 ID；伪造 ID 会被剔除。模型报告的 confidence 没有经过概率校准。

排序默认：

```text
0.20 × log(1 + citation_count)（候选集内归一化）
+ 0.15 × log(1 + citation_count / 发表年限)（候选集内归一化）
+ 0.30 × 领域相关度
+ 0.10 × 被高相关候选论文引用的次数（候选集内归一化）
+ 0.25 × LLM 核心性判断
```

无 LLM 判断时，相关度回退为标题（80%）与摘要（20%）的关键词覆盖率，**尚未实现 embedding 语义检索**。无引用量、年份或候选集引用信号时，对应项不参与，剩余权重重新归一化。共享引用仅统计检索候选集中的参考文献，**不是全库共引分析**。每篇返回综合 score、解释 reason 和实际参与的 signals，最多选 8 篇（可配置 1–10）。这些分数是启发式候选集排序，跨领域不可直接比较。

离线演示使用预设阅读优先级与相关度，书目来自 Crossref/arXiv，未伪造引用次数。见 [演示来源说明](backend/app/data/SOURCES.md)。

## 缓存与错误行为

SQLite 默认文件为 `backend/data/field_navigator.sqlite3`，由 `DATABASE_PATH` 配置。完整结果在 `fields`、`papers`、`field_relations`、`field_core_papers` 四表中同事务保存；`analysis_artifacts` 独立保存检索结果、已验证的地图和论文评价。已有数据库自动增量建表，不清空旧数据。

完整结果缓存包含模式、规范化领域和配置指纹，有效期默认 7 天；自动失败回退仅缓存 5 分钟。检索结果默认保存 24 小时（`SEARCH_CACHE_TTL_HOURS`），地图与评价按证据内容、模型、思考设置和提示词版本隔离。修改排序权重仅重排，失败重试复用成功阶段，各层同键请求有单进程锁。失败阶段与未完成的整图不写入对应缓存，刷新失败保留旧完整结果。“重新分析”跳过全部缓存层。所有缓存键不保存 key。

前端在当前会话中复用已分析节点，同领域请求合并；分析期间可返回缓存、探索其他领域，在后台列表查看进度或取消当前请求，旧请求完成不会抢占当前页面。刷新页面后由 SQLite 返回结果。localStorage 只记录最近领域名称和数据模式（最多 50 条）；JSON 只导出完整结果，不包含 key。二层图只显示已分析的邻居，不自动发出批量 API 请求。

遇到 OpenAlex 429 直接提示，避免在预算耗尽时连续重试；5xx 最多短暂重试一次。请求有超时。无候选论文、模型拒绝、schema 不合格都会显示可重试错误。演示节点不会伪装成实时分析。

## 验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
cd ../frontend
npm test
npm run build
```

自动化测试覆盖递归探索、叶节点、规范化缓存、SQLite 持久化与过期、配置隔离、并发请求、刷新失败保留旧值、无结果与输入验证、OpenAlex 合约和限流、排序信号、结构化模型响应、无效证据过滤以及演示模式不调用真实模型。另覆盖不支持结构化输出时的自动兼容、显式格式设置、错误不盲目重试、独立模型超时及无效 JSON mode 结果不入库。测试使用项目内临时目录，避开系统临时目录权限差异。

浏览器人工验收清单：根领域 → 子领域 → 子子领域；返回缓存；刷新页面后恢复；分支/前置切换；图谱放大与缩放；筛选；论文理由展开；外链；导出；实时模式错误提示。

本次实际完成了上述探索、缓存、筛选、详情和 390px 窄屏检查，并验证实时模式的 429 提示。导出弹窗中的 JSON 已解析校验；内置浏览器未上报文件下载完成事件，下载落盘尚未确认，弹窗提供了可直接复制的完整 JSON。

当前未实现 PDF、RAG、账户、云数据库或自动综述。下一步应首先用真实 LLM + OpenAlex 对多种领域建立小型人工评测集，检验拆分与核心论文选择质量，再替换算法。
