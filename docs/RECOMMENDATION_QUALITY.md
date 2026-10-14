# 推荐质量说明

这份说明记录 Field Navigator 已完成公开评测中的可核对结果和证据边界。v12 与 v13 的两组真实评测均已完成；v13 后续语义复核发现两条关系范围错误，因此 v13 只作为历史 reading-starter 记录。v14 两组真实运行均已完成 6/6。基于公开 metadata 的 agent 复核未发现本轮实质范围或科学阻断，结果适合作为 reading 起点公开草稿；这不等同人工专家复核、付费意愿验证或 held-out 测试。文档不把一次运行或自动审查写成专家结论。

## 固定评测结果

评测使用 6 个公开科研问题和 28 个文献锚点。它们是开发期调参 fixture，不是 held-out 测试集；锚点用于检查候选召回和核心排序是否覆盖预先记录的来源，不表示列表穷尽某个领域。`candidate` 表示锚点出现在本轮候选集合中，`top-8` 表示它进入该 case 的最终核心推荐前 8 项。统计是基于公开来源的 agent 审查，不是领域专家人工评审。

候选召回和最终推荐必须分开读：候选召回保留所有 case 的候选池，即使该 case 随后在地图或审查阶段失败；`live-complete` 只包括真实运行完整完成并有最终核心列表的 case。下表同时给出按 case 的 `macro` 平均与合并锚点后的 `pooled` 比例，不能把一个比例当成另一个比例。`live-complete top-8` 的分母只包含完整 case 的锚点，括号内补充全部 case 的同一 top-8 命中数。

| 轮次 | 完整 case | 候选召回（全部 case，macro；pooled） | 候选召回（live-complete，macro；pooled） | live-complete top-8 锚点覆盖 | 失败轮次记录 |
| --- | ---: | --- | --- | --- | --- |
| baseline | 5/6 | 0.3333；9/28 = 0.3214 | 0.3600；8/23 = 0.3478 | 8/23 = 0.3478（全部：8/28） | TBG：LLM JSON schema 校验失败 |
| after-v1 | 5/6 | 0.3667；10/28 = 0.3571 | 0.4400；10/23 = 0.4348 | 9/23 = 0.3913（全部：9/28） | PSC：LLM JSON schema 校验失败 |
| after-v2 | 4/6 | 0.5667；16/28 = 0.5714 | 0.6000；11/18 = 0.6111 | 4/18 = 0.2222（全部：4/28） | KTaO3、PSC：`CoreAuditBatch` 验证未完成 |
| after-v3 | 6/6 | 0.5333；15/28 = 0.5357 | 0.5333；15/28 = 0.5357 | 14/28 = 0.5000（全部：14/28） | 无失败 case |
| after-v4 | 5/6 | 0.5667；16/28 = 0.5714 | 0.5300；13/24 = 0.5417 | 12/24 = 0.5000（全部：12/28） | NHSE：`subfields` 数量 8 溢出 |
| after-v5 | 4/6 | 0.6417；18/28 = 0.6429 | 0.7250；14/19 = 0.7368 | 13/19 = 0.6842（全部：13/28） | NHSE：LLM 响应无效或网络异常；PSC：独立证据审查未完成 |
| after-v6 | 5/6 | 0.5583；16/28 = 0.5714 | 0.6200；15/24 = 0.6250 | 15/24 = 0.6250（全部：15/28） | RAG：第 4 条及以后 `evidence_quotes` 超出 schema |
| v6 scoped（scope-check） | 5/6 | 0.5333；15/28 = 0.5357 | 0.5200；12/23 = 0.5217 | 11/23 = 0.4783（全部：11/28） | KTaO3：`prereq=6`、`subfields=11` 超过 raw 10 容量；范围诊断历史行 |
| after-v7（canonical） | 5/6 | 0.6417；18/28 = 0.6429 | 0.6100；14/23 = 0.6087 | 12/23 = 0.5217（全部：12/28） | TBG：LLM JSON schema 校验失败 |
| scope-check-v7（scoped） | 6/6 | 0.4667；13/28 = 0.4643 | 0.4667；13/28 = 0.4643 | 12/28 = 0.4286 | 无失败 case |
| after-v8（canonical） | 6/6 | 0.6000；17/28 = 0.6071 | 0.6000；17/28 = 0.6071 | 8/28 = 0.2857 | 无失败 case，但语义复核发现范围错误 |
| scope-check-v8（scoped） | 6/6 | 0.5417；15/28 = 0.5357 | 0.5417；15/28 = 0.5357 | 11/28 = 0.3929 | 无失败 case，但语义复核发现范围错误 |
| after-v9（canonical，历史） | 6/6 | 0.5667；16/28 = 0.5714 | 0.5667；16/28 = 0.5714 | 9/28 = 0.3214 | 无失败 case |
| scope-check-v9（scoped，历史） | 5/6 | 0.6500；18/28 = 0.6429 | 0.6300；15/24 = 0.6250 | 11/24 = 0.4583（全部：11/28） | NHSE：论文评价带空字段名，`extra_forbidden`；按 schema 拒绝 |
| after-v10（canonical，历史） | 5/6 | 0.6417；18/28 = 0.6429 | 0.6500；15/23 = 0.6522 | 10/23 = 0.4348（全部：10/28） | TBG：模型响应 JSON 无效，未保存失败阶段 |
| scope-check-v10（scoped，历史） | 6/6 | 0.5917；17/28 = 0.6071 | 0.5917；17/28 = 0.6071 | 10/28 = 0.3571 | 无失败 case，但仍发现摘录覆盖不足 |
| after-v11（canonical，历史） | 5/6 | 0.6333；18/28 = 0.6429 | 0.6000；14/23 = 0.6087 | 7/23 = 0.3043（全部：7/28） | Prime editing：模型响应非法 JSON，未生成最终列表 |
| scope-check-v11（scoped，历史） | 6/6 | 0.5333；15/28 = 0.5357 | 0.5333；15/28 = 0.5357 | 9/28 = 0.3214 | 无失败 case |
| after-v12（canonical，历史） | 6/6 | 0.5250；15/28 = 0.5357 | 0.5250；15/28 = 0.5357 | 9/28 = 0.3214 | 运行完成；语义复核发现 RAG 数值泛化、数量摘录残缺和合法百分比被误判 |
| scope-check-v12（scoped，历史） | 6/6 | 0.5417；15/28 = 0.5357 | 0.5417；15/28 = 0.5357 | 4/28 = 0.1429 | KTO 规划降级为 1 条基础检索；语义复核问题见下文 |
| after-v13（canonical，历史） | 6/6 | 0.4917；14/28 = 0.5000 | 0.4917；14/28 = 0.5000 | 8/28 = 0.2857 | 无运行错误、超时或演示回退；后续语义复核发现两条关系范围错误 |
| scope-check-v13（scoped，历史） | 6/6 | 0.5750；16/28 = 0.5714 | 0.5750；16/28 = 0.5714 | 11/28 = 0.3929 | 无运行错误、超时或演示回退；后续语义复核发现两条关系范围错误 |
| after-v14（canonical，当前） | 6/6 | 0.5917；17/28 = 0.6071 | 0.5917；17/28 = 0.6071 | 13/28 = 0.4643 | 运行完成；无错误、超时或演示回退；公开 metadata agent 复核未发现实质阻断 |
| scope-check-v14（scoped，当前） | 6/6 | 0.6000；17/28 = 0.6071 | 0.6000；17/28 = 0.6071 | 9/28 = 0.3214 | 运行完成；无错误、超时或演示回退；公开 metadata agent 复核未发现实质阻断 |

baseline、after-v1 至 after-v8 的失败轮次保留在表中，没有挑选各轮最佳 case 代替整轮结果，也没有把 pooled 比例误写成 macro。after-v7 的 canonical 与 scoped 是两个独立角度，不能拼成一轮或互取最佳 case；PSC 仍是经典漏召回例子（after-v7 为 1/5，scope-check-v7 为 0/5；v8 两个角度的逐 case 命中见下表）。after-v6 的 RAG 失败是 `evidence_quotes` schema 容量问题；后续 raw quote allowance 调整为 8，并先过滤无效 ID，留下 3 条合格记录进入 audit/public，这属于修复链路记录，不改写 after-v6 行。表中的 top-8 只表示锚点是否进入最终核心列表，不能替代逐条来源审查；gold-anchor recall 也不能替代核心推荐精度。after-v8 的 canonical top-8 为 8/28，与 baseline 持平，只能说明候选覆盖和运行稳定性，不能写成核心精度提升或专家质量证明。全部 fixture 仍是开发期调参数据，不是 held-out 测试集，不能据此声称跨领域泛化。

v8 两个角度的逐 case 结果如下；六个 case 均有完成记录，candidate 与 top-8 仍分别按各自运行统计。

| case | after-v8 candidate | after-v8 top-8 | scope-check-v8 candidate | scope-check-v8 top-8 |
| --- | ---: | ---: | ---: | ---: |
| KTaO3 interface superconductivity | 5/5 | 1 | 5/5 | 3 |
| one-dimensional NHSE | 3/4 | 2 | 3/4 | 3 |
| magic-angle TBG superconductivity | 4/5 | 3 | 4/5 | 4 |
| PSC stability | 1/5 | 1 | 0/5 | 0 |
| prime editing efficiency | 3/5 | 1 | 1/5 | 0 |
| RAG hallucination evaluation | 1/4 | 0 | 2/4 | 1 |

历史 v9 的两个角度使用同一固定后端源码，真实 OpenAlex 与配置模型，串行运行，每个 case 的时间上限为 240 秒；case 不自动重跑，LLM 非法输出不进行业务重试，也不使用演示回退。OpenAlex 5xx 仍遵循服务层既有的至多一次 HTTP 重试。该轮发生了 1 次正确拒绝的非法模型输出，未静默丢弃空字段名或拼入其他轮的成功结果。该轮主题核心锚点覆盖为 9/28，初始轮为 8/28；这点变化不足以证明核心科学精度改善。具体问题组的 NHSE 失败仍计入 6 个 case；不能把完成 case 的 11/24 写成全部 case 的成功率。

| case | after-v9 candidate | after-v9 top-8 | scope-check-v9 candidate | scope-check-v9 top-8 |
| --- | ---: | ---: | ---: | ---: |
| KTaO3 interface superconductivity | 5/5 | 5 | 5/5 | 5 |
| one-dimensional NHSE | 3/4 | 2 | 3/4 | 失败，无最终列表 |
| magic-angle TBG superconductivity | 3/5 | 0 | 3/5 | 3 |
| PSC stability | 1/5 | 1 | 0/5 | 0 |
| prime editing efficiency | 3/5 | 1 | 4/5 | 3 |
| RAG hallucination evaluation | 1/4 | 0 | 3/4 | 0 |

PSC 的经典来源仍明显漏召回。TBG 主题轮中部分经典论文已进入候选，但因摘要不足被核心审查移出；系统没有仅凭题名补写具体贡献。这会降低核心覆盖，也说明需要继续改善可核验元数据的可用性。RAG 的候选锚点增加没有转化为核心覆盖，检索与核心选择仍需进一步优化。

历史 v9 主题组核查了 9 条 DataCite 注册记录；具体问题组核查了 3 条 arXiv 与 13 条 DataCite 记录，其中 2 条 RAG 候选的索引身份元数据被更正。两组均没有报告缺失/未解析的请求标识。这只说明这些请求标识的核验结果，不说明所有候选均经过官方来源核验。v11 canonical 核查了 17 条 DataCite 记录（4 个 DOI 批次、无 arXiv 记录），其中 2 条 RAG 候选被更正；scoped 核查了 13 条 DataCite 记录（4 个 DOI 批次、无 arXiv 记录），其中 2 条 RAG 候选被更正。两组都没有缺失或未解析的请求标识。

v9 逐条语义复核还发现：一篇法律 AI 工具评测论文被写成了评测者可靠性证据；部分百分比或倍数没有出现在展示摘录中；prime editing 的效率摘录被外推为保真度提升；TBG 的关联母态被过强地表述成配对机制。这些问题表明即便摘要审查通过，自动生成的理由仍可能混淆研究对象或具体结果。v9 没有被写成专家质量验收通过。

v10 中，一维/物种/层数混用、保真度外推和多数数值问题没有再出现；但仍有“seven-fold”和“41 种组合”漏过数量检查，部分关系的理由借用了没有展示摘录的论文正文元数据。TBG 主题 case 的原始模型输出发生 JSON 解析失败；具体问题组的六 case 完成不代表主题组也完成。这轮同样保留实际问题，不用它宣称完整语义验收。

v11 两组继续使用同一固定源码快照、真实 OpenAlex 和配置中的兼容模型，每个 case 串行运行、时间上限 240 秒；case 不自动重跑，LLM 非法输出不进行业务重试，也不使用演示回退。OpenAlex 5xx 仍遵循服务层既有的至多一次 HTTP 重试。canonical 组 5/6 完成，候选锚点为 18/28，按 case 的候选 macro 为 0.6333，完整 case 为 14/23（macro 0.6000），前 8 命中为 7/23（全部 case 为 7/28）；唯一失败是 Prime editing case 的非法 JSON。scoped 组 6/6 完成，候选锚点为 15/28，macro 为 0.5333，前 8 命中为 9/28。v11 的逐 case 结果如下：

| case | v11 canonical candidate | v11 canonical top-8 | v11 scoped candidate | v11 scoped top-8 |
| --- | ---: | ---: | ---: | ---: |
| KTaO3 interface superconductivity | 5/5 | 5 | 5/5 | 5 |
| one-dimensional NHSE | 2/4 | 0 | 2/4 | 1 |
| magic-angle TBG superconductivity | 4/5 | 1 | 3/5 | 0 |
| PSC stability | 1/5 | 1 | 0/5 | 0 |
| prime editing efficiency | 4/5 | 失败 | 3/5 | 3 |
| RAG hallucination evaluation | 2/4 | 0 | 2/4 | 0 |

canonical NHSE 的问题描述是宽泛主题，没有一维限制，因此其中的高维论文不能被判作范围错误；scoped NHSE 才按一维约束过滤。v11 的语义复核促成了几项实际收紧：地图或分支的 `corrected_name` 会重新通过范围门；关系理由只能使用自己的已核对摘录；核心审查只读取每条推荐自己的已核对摘录和题名/ID 上下文，并展示同一份完整摘录；数值、结果类型和理论/因果标签继续以摘录为边界。这样会减少跨论文借证和过度断言，也可能在摘要稀疏或摘录不足时增加假阴性。它仍不是 PDF、全文引文或专家语义证明。

v12 两组真实运行均完成 6/6 case；case 不自动重跑，LLM 非法输出不进行业务重试，也不使用演示回退，OpenAlex 5xx 仍遵循服务层既有的至多一次 HTTP 重试。canonical 的候选锚点为 15/28（macro 0.5250），前 8 命中为 9/28；逐 case 为 KTaO3 5/5、NHSE 2/4、TBG 3/5、PSC 1/5、prime editing 3/5、RAG 1/4，前 8 命中依次为 5、1、0、1、2、0。scoped 的候选锚点为 15/28（macro 0.5417），前 8 命中为 4/28；KTO 的规划阶段只有 1 条检索路径，系统按基础主题检索降级，没有猜测同义词或进行 LLM 重试。v12 的 canonical 与 baseline 前 8 锚点覆盖从 8/28 到 9/28，只是本组 fixture 的 anchor coverage 变化，不能写成核心精度或长期召回提升；scoped 的核心覆盖为 4/28，下降必须保留。

v12 canonical 与 scoped 各核验 15/15 个 arXiv 标识，DataCite 为 0；scoped 运行中有 2 条 RAG 索引身份被更正，canonical 为 0。语义复核发现：RAG 的 Kendall tau/排名数值没有限定在论文具体评测设置中；`7,663` 的数量摘录在去除不受支持的结果时留下残缺文本；合法的 `17%–33%` 被错误当成否定或不支持的数值。这些是实际科学表达问题，触发了 v13 的数值归一化和审查修复；v12 不能写成质量验收通过。

v13 两组历史真实运行均完成 6/6 case，所有 case 均完成 3 条检索路径和 5 个 LLM 批次，没有运行错误、超时或演示回退。canonical 候选锚点为 14/28（macro 0.4917），前 8 命中为 8/28；逐 case 的 candidate/top-8 为 KTaO3 5/5、5，NHSE 2/4、1，TBG 3/5、0，PSC 0/5、0，prime editing 3/5、2，RAG 1/4、0。scoped 候选锚点为 16/28（macro 0.5750），前 8 命中为 11/28；逐 case 为 KTaO3 5/5、5，NHSE 3/4、2，TBG 3/5、3，PSC 0/5、0，prime editing 3/5、1，RAG 2/4、0。canonical 前 8 锚点覆盖与 baseline 同为 8/28，不能写成核心覆盖提升；scoped 的候选和核心覆盖变化也不能替代精度、专家判断或跨领域泛化验证。

v13 本轮按请求标识核验了 canonical 的 13 条 arXiv 记录和 scoped 的 14 条 arXiv 记录，DataCite 均为 0；canonical 没有身份更正，scoped 更正 3 条（TBG 1 条、RAG 2 条）。两组均没有 missing/unresolved 标识。这些数字只说明请求标识的核验结果，不能声称所有候选论文都经过官方来源核验。后续语义复核发现两条实际范围错误：1D NHSE 分支的关系摘录明确写成 `2D acoustic higher-order topological insulator`，却被全文另一处 1D 背景绕过范围门；哺乳动物 prime editing 分支的 RNP delivery 摘录实际写的是 zebrafish embryo，植物限定规则没有挡住这一非哺乳动物证据。两条错误都应以关系自己的实际摘录判为范围不符，不能用全文另一段 1D 或 mammal 背景补证。v13 只能作为可追溯的 reading-starter 评测记录，不能写成完整 scientific accuracy 通过。

v14 两组真实运行均完成 6/6，没有运行错误、超时或演示回退。canonical 候选锚点为 17/28（macro 0.5917），前 8 命中为 13/28；scoped 候选锚点为 17/28（macro 0.6000），前 8 命中为 9/28。逐 case 的 candidate/top-8 如下：

| case | v14 canonical candidate | v14 canonical top-8 | v14 scoped candidate | v14 scoped top-8 |
| --- | ---: | ---: | ---: | ---: |
| KTaO3 interface superconductivity | 5/5 | 5 | 5/5 | 4 |
| one-dimensional NHSE | 2/4 | 2 | 2/4 | 1 |
| magic-angle TBG superconductivity | 4/5 | 1 | 4/5 | 1 |
| PSC stability | 1/5 | 1 | 1/5 | 0 |
| prime editing efficiency | 4/5 | 4 | 3/5 | 3 |
| RAG hallucination evaluation | 1/4 | 0 | 2/4 | 0 |

canonical 的 Prime editing 问题是宽泛主题，没有哺乳动物限制；scoped Prime editing 才带有 mammal 限制。NHSE 同样区分宽泛 canonical 问题和明确一维的 scoped 问题，不能把两组的候选或核心覆盖直接当作同一范围下的精度比较。此前的 2D/1D 与 zebrafish/mammal false positive 在 scoped v14 已消失，RAG 数字限定、`7,663` fragment 和 tool-vs-evaluator 区分保持修复。canonical 的 13/28 top-8 相比 baseline 的 8/28 只能说明这一轮 fixture 的锚点覆盖变化，不能证明专家 precision、长期召回或科学准确性；PSC 和 RAG 的核心覆盖仍弱，经典漏召回及单轮波动必须保留。仍有少量定量值被保守替换、理论标签噪声和短摘录造成的假阴性，不能宣称彻底消除错误。

v14 来源核验按请求标识统计：canonical 核验 8 条（arXiv 5、DataCite 3），身份更正 0；scoped 核验 15 条，全部为 DataCite，身份更正 2 条（RAG）。两组均没有 missing/unresolved 标识。这只说明请求标识的核验结果，不能声称所有候选论文都经过官方来源核验。另有 312 条出处引用（canonical 148、scoped 164）与实际送出的题名/摘要匹配，0 mismatch；这是出处匹配检查，不是 entailment/proof，也不代表 312 条都经过官方元数据核验。基于公开 metadata 的 agent 复核未发现本轮实质范围或科学阻断，结果适合作为 reading 起点公开草稿；这不等同人工专家复核、付费意愿验证或 held-out 测试。

## 运行时质量链路

一次未命中完整缓存的真实 LLM 探索包含 5 个有界批次：

1. 检索规划；
2. 领域地图生成；
3. 论文评价；
4. 独立地图语义审查；
5. 排序后的核心论文独立审查。

默认最多检索 3 条路径，每条最多 40 条记录，原始结果合计最多 120 条；去重合并后送入模型的候选池最多 40 篇。研究问题上下文参与检索规划、候选筛选、排序、生成和审查，且进入缓存键，因此不同范围的问题不会复用同一份完整分析。

候选预算截断前先对完整交错流做规范记录/alias 去重，避免重复版本消耗名额。每条成功路径最多保留两个较后排名的样本，原始问题首项与基础路径头部受保护；基础路径仍保留有限的关键词覆盖选择。这用少量中间排名的候选换取较后结果的覆盖，不保证恢复某篇经典论文，也没有使用评测锚点的标题或 DOI 作为生产规则。规划失败时保留 exact-topic 的基础引用检索 lane 作为确定性降级，不猜测同义词，也不因规划失败重试 LLM；v12 scoped 的 KTO case 实际触发了这一降级。

来源核验由 `LiteratureRetriever` 连接 `ArxivMetadataVerifier` 完成。候选中的 arXiv 标识会去掉版本号并按官方 Atom API 批量查询；一个批次中没有返回的标识只进行一次按 exact DOI 的 DataCite 注册元数据 batch fallback，不把 fallback 当作对原接口的业务 retry。DataCite 只接受请求中的 exact DOI，未知记录会被忽略。来源字段和摘要来源记录保留供追溯，并进入分析 payload；界面区分 arXiv 摘要与 DataCite 注册摘要。整个步骤只核验题名、摘要、作者、年份、DOI 等元数据，不读取 PDF 或全文。

身份冲突时保留产生候选的主 work ID 和来源记录。安全的预印本路径可以按官方题名修正索引元数据，同时清除不属于该身份的 `citation_count` 和 `referenced_works`；已发表 work 不会被不匹配的预印本链接覆盖。版本合并保留规范记录自己的引用量，不从另一版本继承引用量。缺失或无法核验的预印本摘要不会继续作为可信语义证据。

每条 relation 的 quote 先做 evidence provenance 核对，再做本条 scope gate。混合范围摘要会过滤被阻断的 quote 及因此失去有效 evidence ID 的项；若整篇摘要的候选 quote 都被 scope 阻断，则删除 relation。地图审查只收到每条关系自己已核对的摘录，以及题名/ID 上下文；不发送可供其他关系借用的整段摘要。地图或分支的 `corrected_name` 会再次通过范围门，并将关系理由收窄到自己的已核对摘录；同 kind 的更名碰撞只保留 `evidence_status` 或 `confidence` 更强的 relation，不拼接两条 relation 的 claims 或摘录。核心审查只读取每条推荐自己已核对的摘录和题名/ID 上下文，不读取整篇摘要或旧理由来补证；最终展示的 quote 也会重新做 scope check，并展示同一份完整摘录。这里的独立审查是分开的模型生成/复核调用，不代表不同模型或人工专家。生成与 audit 都显式区分 dimension、layer、species、task 四个 scope 维度。最终 reading-starter 的范围判断以实际送出的 own quote 为准；如果摘录本身明确冲突，不能引用全文另一段背景、旧理由或另一篇论文的摘要来补回一维、物种等范围。逐字摘录必须出现在对应标题或摘要中；这是来源追溯检查，不是全文验证，也不等同语义蕴含证明。审查失败时保守降级并保留警告，不把未完成审查结果写成完整缓存；更严格的归属门可能带来更多假阴性。

兼容模型的 JSON transport 允许完整 `json` fence 去壳；只有原始解析明确因字符串内 invalid escape、invalid Unicode escape 或 raw control character 失败时，才在字符串级别转义这些字符。合法 JSON 保持原样。auto 只在明确表示当前模型/服务不支持 `response_format` 或 `json_schema` 时回退到 `json_object`；鉴权、限流和 schema 内容错误不重试。缺引号/括号、尾随 commentary、多段 JSON 不会被猜测修补或截取；Pydantic 业务 schema、ID/verdict/confidence 以及逐字摘录审查不因 transport 兼容而放宽。

JSON-mode 的 raw presentation 预算与业务 schema 分开：模型每组最多返回 20 条关系、每条关系最多 8 条 evidence quote，以容纳有界的长列表；每条记录仍逐项校验 type、ID、confidence 和 quote 格式。canonical + dedup 后 public 保留 5/7，另有 3 条 quote 进入复审，系统不会自行补写证据。这是受限的展示容量配置，不是业务 schema 的泛化放宽。

核心审查的 `insufficient` 一律移出核心列表，题名重合不会推翻审查结论；只有 `direct` 且有可逐字核对的题名摘录时，才可保留为明确标注的弱线索。生成和审查提示词要求将 `nodeless` 译为“无节点/全能隙”，不译成“无能隙”。[PRB 术语来源](https://journals.aps.org/prb/abstract/10.1103/PhysRevB.102.024523)只用于术语核对，不为任何 KTaO3 结论背书。`ML prediction` 只有同一句明确写出机制或因果语境时才触发理论标签，否则保持研究方向。当前 `quality_revision=10`、`PROMPT_VERSION=19`、`RETRIEVAL_VERSION=12` 纳入分析产物和缓存指纹，避免旧版本缓存复用。

v8 虽然两组均运行完成，逐条语义复核仍发现三类错误：把 Chern/量子霍尔主体论文作为一维链的核心证据；用植物 prime editing 论文支持哺乳动物问题中的蛋白工程分支；把某项数值任务的失败召回率泛化成通用 LLM judge 可靠性。因此 v8 没有被当作学术质量验收通过。

修复后增加了模型审查之前的范围规则：仅限一维、双层或哺乳动物的明确问题，会过滤标题与元数据中明显冲突的维度、层数和物种，并在核心/关系审查入口再次检查。v14 进一步让每条 relation 先通过 evidence provenance 核对再做本条 quote 的 scope gate；混合摘要过滤被阻断 quote 及失去有效 evidence ID 的项，整篇摘要的候选 quote 全部被阻断时删除 relation，核心最终 quote 也重新做 scope check。有限的非哺乳动物 taxon 和明确 cross-species 问题按显式例外保留。比较研究、任意维度理论、明确的跨维映射或泵浦问题保留例外。规则不含评测论文标题或 DOI；它们是有限的文本规则，不能替代完整语义理解。规则识别到包含召回率、准确率、精确率、F1、失败率等数值的评测摘录时，理由加上“在所引论文的具体评测设置中”的限定，不外推其他模型或任务；该文本规则不保证识别所有指标表达。效率、保真度、纯度和 judge 可靠性也不能互相推出。

v9 后进一步加入了具体结果检查：识别到的百分比、倍数、比例和有限的实验计数若未出现在已核对摘录中，会去掉未核对数值并说明限制；合法的中英文 fold/倍数表达、one–ten 英文倍数与范围可以对应，数值摘录对应的理由限定为原论文的具体设置。v13 的有限模式扩展到 correlation、rank metric、分组计数以及 Unicode 百分号/范围表达，并保留带具体评测设置的 quoted settings；它不宣称覆盖任意自然语言计数或通用 NLP 语义。年份、维度标签和模型标识不当作测量计数。保真度、编辑产物纯度及特异性/脱靶结果分别检查，效率摘录不能同时放行其他结果。仅评测 AI 工具的准确率或幻觉率，不代表证明了评价者本身可靠；对此保留研究方向，但收窄不支持的主张。未来工作和明确未测量的表述会保留。

这些仍是有限的文本模式与模型审查，不能识别所有指标、否定关系或科学限定语。一维问题可以使用任意维度理论，但会提示核对模型与适用条件；关联母态不自动证明配对机制。明确因果方向中的理论/假说限定会保留为候选解释，即使限定语位于另一句。方法规范、共识声明或报告标准可以作为入门背景，不能被写成原始实验发现。

收藏清单收到来源核验后的题名修正时更新论文元数据，保留用户笔记、阅读状态和收藏时间。引用量始终属于所选的规范记录，不继承错配索引或另一版本的数值。

## 推荐结果的解释边界

- 只有题名的论文最多作为弱线索，不能确认具体机制、指标或贡献。
- 有摘要摘录且通过独立审查的结果，才以摘要中的范围内贡献作为推荐理由。提示词和审查要求保留 proposed、consistent with 等限定语；自动审查仍可能遗漏，不能当作领域共识。
- 关系的 `supported` 表示有摘要覆盖该研究方向，不表示机制已经被证实。界面另标出“理论 / 候选解释”或“仅题名线索”；成熟度提示也只是对实际摘录与审查理由的保守规则检查。
- 核心审查返回 `direct`、`context`、`off_topic` 或 `insufficient`。`context`、`off_topic` 和 `insufficient` 都会移出核心列表；题名重合不会推翻审查结论。只有 `direct` 且有可核对的题名摘录时，才可保留为弱阅读线索，贡献不予确认，得分至多 0.65；角色为 `unknown`，明确综述保留 `review`。结果可能少于 8 篇。
- `review` 最多保留 1 篇；`unknown` 可以保留，但不会因为角色未知而自动获得学术权威含义。
- 候选池、启发式排序和模型评分都依赖当前检索结果，分数不能跨领域直接比较。

系统仍未实现 PDF 解析、全文引文核证、RAG 问答、真正的 citation network、自动学术审稿或自动综述。推荐结果适合作为可追溯的阅读起点，使用者仍需打开原始来源并自行判断。

## 本地复核

v14 冻结快照已通过后端 207 项全量测试（另有 2 个既有依赖弃用警告）；前端 35 项测试、TypeScript 检查和 Vite 生产构建通过。最终浏览器视觉验收因当前策略拒绝未执行。v12 与 v13 的真实评测和失败记录均保留为历史；v13 的两条关系范围错误已触发 v14 的 quote-level scope gate 修复。v14 两组真实运行已完成 6/6，无错误、超时或演示回退。基于公开 metadata 的 agent 复核未发现本轮实质范围或科学阻断，结果适合作为 reading 起点公开草稿；这不等同人工专家复核、付费意愿验证或 held-out 测试。评测轮次的原始运行数据不在公开文档中附带，避免把内部路径、请求内容或配置泄露到参赛材料。

## 官方来源

- OpenAlex [搜索说明](https://help.openalex.org/api/searching/)
- OpenAlex [Works 数据说明](https://help.openalex.org/data/works/)
- OpenAlex [Work types 词汇](https://help.openalex.org/data/work-types/)
- OpenAlex [Locations 说明](https://help.openalex.org/data/locations/)
- OpenAlex [过滤说明（含 type 与 locations 字段）](https://help.openalex.org/api/filtering/)
- arXiv [API user manual](https://info.arxiv.org/help/api/index.html)
- DataCite [REST API](https://support.datacite.org/docs/rest-api)
- DataCite [Queries and filtering](https://support.datacite.org/docs/api-queries)
- OpenAI [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

这些官方文档用于说明接口、Works 元数据、来源位置/类型字段和结构化输出约束，不构成任何论文结论或专家评审。
