# Field Navigator

面向学生和课题组的研究入门工作空间：中文或英文问题 → 方向解析与用户确认 → 查找论文 → 提取前置领域与研究分支 → 展示知识地图 → 查看证据、收藏笔记、导出简报 → 刷新后继续。论文是领域节点下的证据与学习材料，图中的主要节点始终是领域。

首次打开只请求本地 `/api/health` 检查服务状态，不自动发起外部解析或探索；用户提交问题后才调用 `POST /api/fields/resolve`，确认方向后再调用 `POST /api/fields/explore/stream`。

本项目按 [Apache License 2.0](LICENSE) 发布。

Docker Compose 部署说明见 [DEPLOY.md](DEPLOY.md)；可将文中的部署指令直接交给自动部署器。

魔搭单容器部署见 [ModelScope部署说明](deploy/modelscope.md)。参赛作品范围、演示路径与交付状态见 [参赛说明](docs/HACKATHON.md)。

界面采用搜索、左侧探索记录、中间分支表与关系图、右侧论文详情布局。支持缩放、拖动画布、放大图谱、置信度筛选、前置/分支显示开关、已分析节点的二层视图、证据展开、阅读清单/笔记、研究简报和 JSON 导出。

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
- 默认 `LLM_RESPONSE_FORMAT=auto`：先请求严格 `json_schema`，仅在服务明确返回当前模型或服务不支持该 `response_format`/`json_schema` 时，改用 `json_object` 重试一次，并在当前后端进程中记住该兼容模式。鉴权、限流、模型名称错误及 schema 内容错误不触发降级。两种模式都通过 Pydantic 校验，拒绝无效结构。
- 兼容模型的 JSON transport 只做两项边界处理：完整的 ` ```json ... ``` ` object 响应去壳，以及原始 JSON 明确因字符串内 invalid escape、invalid Unicode escape 或 raw control character 失败时的字符串级转义修复。合法 JSON 保持原样；缺引号/括号、尾随说明、多段 JSON 不会被修补或截取。该兼容层不放宽 Pydantic 业务 schema、证据 ID、逐字摘录或独立审查规则。
- JSON-mode 的 raw presentation 预算与业务 schema 分开：模型每组最多返回 20 条关系、每条关系最多 8 条 evidence quote，以容纳有界的长列表；每条记录仍逐项校验 type、ID、confidence 和 quote 格式。canonical + dedup 后 public 保留 5/7，另有 3 条 quote 进入复审，系统不会自行补写证据。这是受限的展示容量配置，不是业务 schema 的泛化放宽。
- 可强制设置 `json_schema`（不自动降级）或 `json_object`。DeepSeek Chat Completions 使用 JSON mode，可选择 `auto` 或 `json_object`。修改 `.env` 后重启后端。[DeepSeek JSON 输出文档](https://api-docs.deepseek.com/guides/json_mode/)
- 模型请求独立使用 `LLM_REQUEST_TIMEOUT_SECONDS`（默认 180 秒），避免分析多篇摘要时被论文检索的 `REQUEST_TIMEOUT_SECONDS`（默认 45 秒）提前中止。
- `LLM_THINKING=auto` 对官方 DeepSeek 关闭思考，对其他服务保留原行为。可设 `low` / `high` 使用 DeepSeek 兼容的思考参数，或设 `provider` 完全遵循服务默认值。`LLM_MAX_TOKENS` 包含推理预算；截断结果不会保存。
- `LLM_ANALYSIS_LIMIT=0` 默认分析全部候选。设为 `16` 可试验代表性候选筛选，界面显示实际分析数量与覆盖限制。完整优化设计、实测和对比工具见 [性能说明](docs/HACKATHON.md)。
- Compose/预览默认使用 `LIVE_REQUEST_BUDGET=30` 和 `LIVE_MAX_CONCURRENCY=2`，分别限制单进程非缓存实时请求次数与并发数；本地开发需显式将相应值设为 `0` 才取消限制，离线演示和有效缓存不受影响。
- 无 `LLM_API_KEY` 时使用 `MockLLMProvider`。预设仅覆盖 NHSE 及其分支；其他领域可以实时搜索论文，但不编造领域关系。

| 界面模式 | 论文来源 | 分析行为 |
| --- | --- | --- |
| 自动 | 优先 OpenAlex；失败时仅对预设 NHSE 领域回退到演示书目 | 有真实论文且配置 LLM 时调用模型，否则明确标注预设拆分 |
| OpenAlex 实时 | 只用 OpenAlex，失败直接显示错误 | 有 key 用 LLM；无 key 用有限的预设拆分 |
| 离线演示 | 内置已核对书目，无网络依赖 | 始终使用预设拆分，即使配置了 LLM key 也不调用模型 |

离线演示可从 `NHSE` 开始：`NHSE` → `Incoherent NHSE` → `Photonic quantum walks`。叶节点会显示无更多分支。真实检索则先提交问题并确认解析出的方向，再开始探索；点击左侧记录或面包屑可返回。

**真实质量评测：** 使用六个领域的公开科研问题和 28 个关键文献锚点，对候选召回、核心推荐、版本重复与分支语义逐项检查。这六个 case 和 28 个锚点是开发期调参 fixture，不是 held-out 测试集；它们用于保留失败证据和比较修复前后行为，不能据此声称跨领域泛化。具体结果、失败轮次与剩余问题见 [推荐质量说明](docs/RECOMMENDATION_QUALITY.md)。链路成功不等于学术质量通过，自动审查也不证明付费意愿。

## 架构与替换点

```text
frontend/src/components/{SearchBar,DirectionChooser,FieldGraph,DetailPanel}.tsx
              ↓ POST /api/fields/resolve（解析与方向确认）
backend/app/api/fields.py → QueryResolver
              ↓ 用户确认后 POST /api/fields/explore/stream（NDJSON，原 JSON 接口仍保留）
              ↓
services/field_explorer.py        只编排步骤、缓存和回退
  ├── providers/base.py           PaperProvider / LLMProvider 协议
  ├── services/literature_retriever.py 有界检索计划、三路召回、合并与候选池
  │     ├── providers/openalex.py       搜索 / 单篇查询 / 引用查询
  │     ├── services/arxiv_metadata_verifier.py 官方元数据身份核验
  │     └── services/paper_quality.py   质量门、版本身份与保守去重
  ├── services/field_decomposer.py 提示词、结构化清洗
  │     ├── providers/llm.py      OpenAI-compatible HTTP transport
  │     └── providers/mock.py     有边界的预设演示
  ├── services/evidence_verifier.py 关系与核心推荐的独立证据审查
  ├── services/paper_ranker.py    独立排序函数和服务
  ├── services/paper_selector.py 可选的代表性候选筛选实验
  └── db/cache.py                SQLite 事务与缓存
```

数据合同在 `backend/app/models/schemas.py` 和 `frontend/src/types/index.ts`。`FieldNode` 包含 summary、prerequisites、subfields、core_papers，并额外返回来源、警告、生成时间和 cache_hit。`FieldRelation.evidence_paper_ids` 标明候选论文证据；`evidence_papers` 返回关系实际引用的候选论文元数据，关系详情可打开原始来源，即使该论文不在核心论文列表中。关系还带有证据状态、逐字摘录和审查警告。`CorePaper.signals` 暴露各评分项，`role`、`evidence_basis` 和 `evidence_quote` 说明它是核心、综述或背景线索，以及推荐理由的元数据依据。

- 替换 OpenAlex：实现 `PaperProvider.search_papers/get_paper/get_citations`，返回 `Paper`，在 `main.py` 注入。
- 替换 LLM：实现 `LLMProvider.generate_structured`，在 `main.py` 注入。
- 改领域拆分：修改 `FieldDecomposer` 的提示词/清洗或替换整个服务，保持 `Decomposition` 合同。
- 改排序：替换 `PaperRanker.rank` 或 `core_paper_score`，保持 `CorePaper` 合同；UI 无须修改。
- 改权重：修改 `.env` 中的 `RANK_*` 即可。

## 当前算法

明确的研究问题会在检索、候选筛选、排序、拆分和缓存中作为范围上下文保留。`LiteratureRetriever` 默认最多使用 3 条互补检索路径（原始问题、锚点/基础工作、替代表述与研究侧面），每条最多 40 条记录，原始结果合计最多 120 条；去重合并后送入模型的候选池最多 40 篇。OpenAlex 结果先经过质量门与保守身份去重，再进入模型。规划失败时保留 exact-topic 的基础引用检索 lane 作为确定性降级，不猜测同义词，也不因规划失败重试 LLM。带有 arXiv 标识的候选由 `ArxivMetadataVerifier` 将版本号归一化后请求官方 Atom API；一个请求批次中缺失的标识只触发一次按 exact DOI 查询的 DataCite 注册元数据 fallback，不把它当作同一接口的业务重试。该链路只核验标题、摘要、作者、年份、DOI 等元数据，不抓取全文。

来源核验会保留候选产生的主 work ID 和来源记录。来源字段和摘要来源记录保留供追溯，并进入分析 payload；界面区分 arXiv 摘要与 DataCite 注册摘要；这两个来源不会被合并成一个无来源的摘要。索引题名与官方记录冲突时，只在安全的预印本身份路径上修正元数据，并清除不属于该身份的 `citation_count` 与 `referenced_works`；遇到不匹配的预印本链接时保留原出版元数据。合并不同版本时不会把一个版本的引用量继承给另一个版本，引用量始终归属于被保留的规范记录。地图或分支生成的 `corrected_name` 会重新通过范围门；同 kind 的更名碰撞只保留 `evidence_status` 或 `confidence` 更强的 relation，不拼接两条 relation 的 claims 或摘录。论文元数据和用户输入作为不可信数据传给模型，提示词要求忽略其中的指令。

一次未命中完整缓存的真实 LLM 探索包含 5 个有界批次：检索规划、领域地图生成、论文评价、独立地图审查和核心论文审查。地图生成与论文评价是分开的批次，地图审查检查关系，排序后的核心论文再接受一次独立审查。每条关系先核对 evidence provenance，再只用自己的实际 quote 做 scope gate；混合范围摘要会过滤被阻断的 quote 及因此失去有效 evidence ID 的项，若整篇摘要的候选 quote 都被 scope 阻断则删除 relation。生成和 audit 都显式保留 dimension、layer、species、task 四个 scope 维度，不把其中一个维度的证据扩大到另一个维度。核心审查也会对最终展示的 quote 再做 scope check，并展示同一份完整摘录；如果自己的摘录明确冲突，不能引用全文另一段背景、旧理由或另一篇论文的摘要来补回一维、物种等范围。有限的非哺乳动物 taxon 与明确 cross-species 问题可按显式规则保留例外，不提供通用 taxonomy 判断。这里的独立审查是分开的模型生成/复核调用，不代表不同模型或人工专家。审查失败会保守地降低召回。摘录是可追溯性检查，不等同全文核证或语义蕴含证明。

评测类摘要的数值检查只使用有限模式，v13 扩展覆盖 correlation、rank metric、分组计数以及 Unicode 百分号/范围表达；只有原摘录同时保留具体评测设置时才保留相应的量化理由。这是保守的引用边界规则，不是对通用 NLP 或任意科学表达的无限语义理解。

检索完成先显示初筛论文；地图完成即显示，论文评价完成再给出最终排序。输入使用短论文 ID，输出后恢复真实证据 ID。简介和理由有长度预算，减少等待。领域必须是概念依赖或有实质内容的研究方向；去掉自身、重复、前置/分支交叉重复。独立审查会删除无支撑关系，把只有题名线索的结果降为弱线索并给出警告；核心审查的 `insufficient` 一律移出核心列表，题名重合不会推翻审查结论，只有 `direct` 且有可逐字核对的题名摘录时，才可保留为明确标注的弱线索。关系实际引用的论文不要求位于核心论文前 8；综述最多保留 1 篇，模型报告的 confidence 没有经过概率校准。

生成和审查提示词要求将 `nodeless` 译为“无节点/全能隙”，不译成“无能隙”。[PRB 术语来源](https://journals.aps.org/prb/abstract/10.1103/PhysRevB.102.024523)只用于术语核对，不为任何 KTaO3 结论背书。`ML prediction` 只有同一句明确写出机制或因果语境时才触发理论标签，否则保持研究方向。

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

完整结果缓存包含模式、规范化领域和配置指纹，有效期默认 7 天；自动失败回退仅缓存 5 分钟。检索结果默认保存 24 小时（`SEARCH_CACHE_TTL_HOURS`），地图与评价按证据内容、模型、思考设置和提示词版本隔离。`quality_revision=10`、`PROMPT_VERSION=19`、`RETRIEVAL_VERSION=12` 进入分析产物和缓存指纹，避免旧版本缓存复用。修改排序权重仅重排，失败重试复用成功阶段，各层同键请求有单进程锁。失败阶段与未完成的整图不写入对应缓存，刷新失败保留旧完整结果。“重新分析”跳过全部缓存层。所有缓存键不保存 key。

前端在当前会话中复用已分析节点，同领域请求合并；分析期间可返回缓存、探索其他领域，在后台列表查看进度或取消当前请求，旧请求完成不会抢占当前页面。刷新页面后恢复本地保存的 complete 快照，最多 8 个；历史最多 50 条，阅读清单最多 100 篇，单条笔记最多 4000 字符。部分分析阶段已经找到的论文可继续在当前界面使用，但未完成整图不写入 complete 快照/缓存。JSON 只导出完整结果，不包含 key。二层图只显示已分析的邻居，不自动发出批量 API 请求。

遇到 OpenAlex 429 直接提示，避免在预算耗尽时连续重试；5xx 最多短暂重试一次。请求有超时。无候选论文、模型拒绝、schema 不合格都会显示可重试错误。演示节点不会伪装成实时分析。

## 验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
cd ../frontend
npm test
npm run build
```

自动化测试覆盖递归探索、叶节点、规范化缓存、SQLite 持久化与过期、配置隔离、并发请求、刷新失败保留旧值、无结果与输入验证、OpenAlex 合约和限流、排序信号、结构化模型响应、无效证据过滤以及演示模式不调用真实模型。另覆盖不支持结构化输出时的自动兼容、显式格式设置、错误不盲目重试、独立模型超时、无效 JSON mode 结果不入库、官方 arXiv/DataCite 元数据核验和版本引用量隔离，以及 JSON transport 的受限字符串修复与拒绝边界。测试使用项目内临时目录，避开系统临时目录权限差异。

浏览器人工验收清单：中文/英文问题 → `POST /api/fields/resolve` → 方向确认 → 探索流；根领域 → 子领域 → 子子领域；证据展开与外链；收藏、已读和笔记；研究简报/JSON 导出；刷新后恢复 complete 快照；分支/前置切换；图谱放大与缩放；筛选；实时模式错误提示。最终浏览器视觉验收因当前策略拒绝未执行，不把它写成已完成。v14 冻结快照已通过后端 207 项全量测试（另有 2 个既有依赖弃用警告）；前端 35 项通过，TypeScript 检查和 Vite 生产构建通过。v13 仍是历史 reading-starter 记录并保留两条关系范围错误；v14 两组真实运行均完成 6/6，无错误、超时或演示回退。基于公开 metadata 的 agent 复核未发现本轮实质范围或科学阻断，结果适合作为 reading 起点公开草稿；这不等同人工专家复核、付费意愿验证或 held-out 测试。

当前本地闭环已经覆盖方向解析、证据查看、阅读清单、笔记、简报导出和刷新恢复。当前仍未实现 PDF、RAG 问答、全文引文核证、真正的论文 citation network、账户、云数据库、自动学术审稿或自动综述；独立审查也不能替代领域专家判断。后续先做人工质量评测和真实用户重复使用验证，再决定算法与收费投入。

当前 v14 的六领域主题组和具体问题组均完成 6/6；两组候选锚点各为 17/28，核心前 8 锚点分别为 13/28 和 9/28。基于题名与摘要的 agent 复核未发现本轮实质范围或科学阻断，适合作为可追溯的阅读起点初稿。经典文献覆盖仍不稳定，尤其是钙钛矿稳定性和 RAG；这些开发期 fixture 与出处匹配不能证明专家准确度、付费产品质量或跨领域泛化。完整分轮结果、失败记录和证据边界见[推荐质量说明](docs/RECOMMENDATION_QUALITY.md)。

## 官方数据与结构化输出依据

检索层使用 OpenAlex 的官方[搜索说明](https://help.openalex.org/api/searching/)、[Works 数据说明](https://help.openalex.org/data/works/)、[Work types 词汇](https://help.openalex.org/data/work-types/)、[Locations 说明](https://help.openalex.org/data/locations/)和[过滤说明](https://help.openalex.org/api/filtering/)；来源核验使用 arXiv 官方 [API user manual](https://info.arxiv.org/help/api/index.html) 与 DataCite 官方 [REST API](https://support.datacite.org/docs/rest-api) 的 [Queries and filtering](https://support.datacite.org/docs/api-queries)。其中 Works 元数据包含来源位置，过滤说明列出 `type` 与 `locations` 等字段。LLM 的结构化响应约束参考 OpenAI 的官方 [Structured Outputs 文档](https://developers.openai.com/api/docs/guides/structured-outputs)。这些来源说明接口和数据字段，不构成论文结论的专家背书。
