# Trupic 视频能力研究｜单张商品图、多段实拍与长视频切片

研究日期为 2026 年 11 月 26 日。本文以当前 Trupic 工作区为基线。上游源码固定为 [ClipForge v0.11.1][cf]、[OpenMontage main@2e003e6][om] 和 [AutoClip main@559f019][ac]。文中的实施顺序与验收口径是本次建议。[播放 15 秒单图口播验证片](./matcha-15s.mp4)

## 1. 从商家的任务决定怎么接

响指出片的入口是手机网页和微信小程序里的营销助理。商家说一句需求，可以沿用店铺、商品和活动资料，同时拿到海报、短片和发布文案。商家确认报价，成品进入自己的作品记录，改活动或换画幅时可以回到原作。因此，视频功能首先要帮助商家少拍素材、把商品讲清楚，并在下次修改时少花钱。视频里的价格、时效、适用条件和行动指引应与同一活动的图文一致。[产品说明](../../../README.md#商家操作) · [对话与交易验收](../../../PRD-验收进度.md) · [业务架构](../../../ARCHITECTURE.md)

Trupic 已能制作 15、30、45 秒的三、五、七镜短片，兼容旧版九秒作品。它能按照框选区域推近商品细节，生成动态环境后在本地合成原图、字层、配乐，并按 24 fps 解码核查。作品已有净画面、字幕、音轨和剪点表。当前短片的声音来自程序配乐。助理的中文朗读可以为口播实验提供音频。现有“参考视频”上传只授权分析节奏，它与商家同意剪进成片的素材应分开管理。[分镜](../../../server/campaign.py) · [曝光商品细节](../../../server/shot_detail.py) · [配乐与合成](../../../server/media.py) · [工程导出](../../../server/film_edit.py) · [参考视频入口](../../../server/reference_assets.py)

| 商家手里的东西 | 想做什么 | 建议让哪个项目发挥作用 | 给商家的结果 |
| --- | --- | --- | --- |
| 一张商品正面图，一项已确认的卖点 | 今天发一条能介绍商品的短片 | ClipForge 的单图带货方式，加上 OpenMontage 的商品镜头约束 | 15 秒原图口播短片、同一活动的发布文案 |
| 商品图，另有几段自己的实拍 | 让顾客看到商品如何使用 | OpenMontage 组织逐镜素材，ClipForge 提供锁镜、换镜和文案节奏的参考 | 实拍演示、原图定版，可只换开场或某个细节镜头 |
| 一段较长的店主播讲、门店讲解或直播 | 找出值得单发的完整回答 | AutoClip 找原话与时间码，Trupic 负责核对商品、活动条件和品牌呈现 | 可回看原片的候选、原声短片、封面和发布文案 |
| 只有一条获授权参考节奏的视频 | 希望自家商品也用类似节奏 | 沿用 Trupic 的切点分析，借 ClipForge 的逐镜对照 | 用自己的商品素材出片。参考片保留为对照 |

## 2. 用 ClipForge 的单图带货流程讲清购买理由

**值得取的是从商品证据写口播、再为每一镜指定真实素材的做法。** 它的脚本接口可以接收已有商品分析，也能把商品图送到所选视觉模型，提出品类、可见包装、卖点与脚本建议。识图失败时脚本仍可继续生成。对 Trupic，应把图上看见的外观、商家确认的经营事实、模型提出的创意分开。杯壁的分层可以直接拍给顾客看，成分、功效、折扣、库存和用户评价则要有商家资料支持。已有商品资料时应复用同一份确认稿，海报、口播和发布文案只改变表达。[商品分析入口][cf-analyze] · [商品分析提示][cf-prompt] · [Trupic 生产时的事实检查](../../../server/app.py)

**“原图出镜”有具体实现边界。** ClipForge 的商品特写模式会安排推进、平移和结尾定版。标成商品原图的镜头可以跳过图库补位。实际合成优先读取该镜已选素材，其次是参考镜指定的商品图，最后回退到项目第一张商品图。如果已经选中了 AI 素材，即使项目中有原图，也可能渲染 AI 画面。它的开头商品露出预检还会读取脚本或旁白提及的商品名。Trupic 应显式把首镜、商品证据镜和购买信息镜绑定到相应原图或授权实拍，并在最终编码的画面里核对商品。只上传正面照片时可以做推近和横移。需要展示背标、开盖或使用过程时，应索取对应角度或实拍。[原图运镜][cf-motion] · [图库跳过条件][cf-stock] · [合成选图优先级][cf-select] · [开场预检][cf-open]

**声音是Trupic 单图短片可以优先补的一环。** 对已审脚本逐镜生成旁白，探测真实语音时长，然后让字幕按说话窗口切换。引擎给词边界时可逐词对齐。只有整段时长时宜按短句分页。配乐在人声期间压低，片尾保留读价格和行动句的时间。超时优先缩短同义口播，涉及新卖点或交易条件则重新确认。ClipForge 普通配音模式会调整镜头长度，淡入淡出也会改变总长。Trupic 应以报价中的时长和 24 fps 时间线为准。上游普通合成只列出 9∶16、16∶9、1∶1，Trupic 现有的 3∶4 等画幅仍走本地构图。[语音与字幕时间线][cf-timeline] · [时长与画幅][cf-compose] · [Trupic 画幅](../../../server/formats.py)

**接法分两层。** 内部对照实验可在隔离实例建项目、上传原图、导入测试口播、绑定每镜素材，再提交合成，按返回的合成编号轮询并下载 MP4 和时间线。导入整段脚本会重新分句估时。正式生产宜保留 Trupic 已审分镜，由本地合成承接音频和字幕。锁镜、保留候选和复制 A/B 版本值得用于“另换一个开头”。商品绑定、配音缓存、版本关系和费用都要能追溯到具体镜头。[脚本导入][cf-import] · [逐镜素材接口][cf-assets] · [版本和锁镜][cf-lock]

## 3. 用 OpenMontage 的导演方法确定每一镜的证据和变化

OpenMontage 的主干是一套由外部 agent 阅读流程和导演指引、调用工具、保存阶段产物的制作方法。它把镜头计划、素材清单和剪辑决策分别记录，最终可用 FFmpeg、Remotion 或 HyperFrames 合成。Trupic 已有任务执行、模型路由和渲染器，优先引入的是导演判断和数据结构。这样网页和小程序仍承接一句话创作，后台却能解释为什么用了这张图、为何要求补一段实拍，以及换镜头会影响哪些素材。[制作架构][om-arch] · [镜头计划][om-scene] · [素材清单][om-assets] · [剪辑决策][om-edit]

商品导演指南把证据分为商品身份、可见角度、表面材质、真实操作及风格参考。例如相机只有正面照，可用原图展示轮廓、推近已标记拨盘，背景可做扫光。要拍翻转机身、打开卡槽或演示防抖，得先有能证明这个动作的素材。导演在每镜写明引用原图、保持项、允许变化、起止画面和验收要求。Trupic 可把这些写入现有分镜与技能版本，视觉审核继续比较成品和实物照片。上游的这些字段表达导演意图，本身不会证明生成图里的商标正确。[商品商业片指南][om-product] · [Trupic 分镜证据](../../../server/shot_detail.py) · [成品审核](../../../server/visual_review.py)

对有多段素材的商家，优先做“哪个动作有证据就剪哪个动作”。比如门店有杯子全貌、倒入抹茶的实拍和成品照三份素材，分别承担当场识别、制作演示和结尾定版。商家说“第二镜换成慢一点的倒茶”，应能定位该镜、保留原版，重用首尾镜。现有云视频背景任务以整条为单位。要实现按镜重做和按镜计费，要先落稳定镜头编号、素材版本与任务缓存。上游的本地观片板适合团队检查导演方案，商家侧只需看当前方案和受影响镜头。[商品导演方法][om-product] · [观片板][om-backlot] · [Trupic 视频任务](../../../server/video_api.py) · [作品修改](../../../server/revisions.py)

## 4. 用 AutoClip 从已有原声中找到能单独发布的一段

AutoClip 处理的是已有视频。可以输入本地文件及 SRT。在缺少字幕时，可以先做本地或已配置的云端转写。快速选段将字幕行号、时间位置和原文送给模型，模型返回起止行、标题、入选理由和分数。程序将行号映射回真实时间，校正边界、筛选并去除重叠候选。无法得到有效选段时，相关路径可回退到大纲、时间线、评分和标题的分步处理。其 CLI 和 MCP 可进一步输出视频、封面、发布文案与打包路径。字幕流程适合有连续解说的素材。无解说的倒饮料、上手试用等实拍，更适合作为 OpenMontage 式镜头素材直接编排。[选段算法][ac-find] · [流程回退][ac-run] · [CLI 与 MCP][ac-cli]

建议先为“店主讲商品／直播里答顾客问题”提供候选。商家能看到推荐标题、原话、原片入出点和上下文，点一下即可试听原声。例如店主说“这款是十九元，周五以后恢复原价”，候选应带上价格条件。如果画面或原话已过期，应换段或重新确认。AutoClip 的长素材选段参数偏向完整回答，常规长素材路径目标 90–180 秒，另有短素材档。Trupic 需要单独处理“完整原声精华”和已报价的 15／30／45 秒广告。访谈式竖裁会优先跟人脸，主播手里的商品、包装和演示动作需要额外保护。构图冲突时可保留原画幅，在边缘补品牌版式。[选段时长][ac-duration] · [自动竖裁][ac-frame]

实施时先从选段结果取时间码、原话和来源，复用 Trupic 的品牌与活动信息生成封面和发布文案。源视频按“可剪入作品”登记，记录所属商家、授权用途和保存期限。长文件需要新上传路径、可恢复处理及容量控制。按源视频缓存转写和候选，同一场直播做两条片不必重新转写。在后台运行 CLI 时可为每个任务设置独立数据目录。采用 MCP 异步任务则需保存任务编号，分别处理部分成功、取消、进程中断和可取回的成品。[CLI 状态与目录生命周期][ac-cli] · [Trupic 当前参考素材入口](../../../server/reference_assets.py)

## 5. 放进 Trupic 的同一项活动里

以茶饮上新为例。第一次，店主只上传一张抹茶拿铁图。助理复用店铺和活动资料，先用全杯让人认出商品，再推近杯壁分层，最后定版并说出“到店点一杯”。第二天店主补拍倒入抹茶的动作，只替换中间一镜。周末又上传一段店主答疑，AutoClip 从原声中找出完整解释，选中后可独立交付，也可用作下一版的证据镜。这三次创作共用商品、活动、原图和已确认事实，新增费用来自本次选择的工作。

| 实施位置 | 建议变更 | 现有承接点 |
| --- | --- | --- |
| 助理与报价 | 依据输入区分商品图、可用于成片的上传片、仅参考节奏的片。把目标、原声／合成配音、时长、画幅、产物数和积分写入确认卡 | [对话策划](../../../server/agent_planner.py) · [签名报价](../../../server/auto_creation.py) |
| 分镜与资产 | 给现有分镜增加稳定编号和用途。每镜引用素材版本、关联卖点、商品保护区域。取自实拍的镜头另存源入出点。可选镜头留下候选与选中状态 | [分镜](../../../server/campaign.py) · [商品证据](../../../server/shot_detail.py) |
| 声音、时间线和交付 | 原声镜保留商家声音，旁白镜复用已审文本。将实测时长、字幕起止和背景音乐混音写入同一时间线，同时生成 MP4、SRT 和剪辑包 | [音频合成](../../../server/media.py) · [剪辑包](../../../server/film_edit.py) |
| 渲染、重试和结算 | 工作进程按镜缓存素材及外部任务号。交付前核查商品、字幕、时长、画幅、原声和促销条件。失败保留可重用的镜头，订单按原有交易规则处理 | [制作与审核](../../../server/app.py) · [视频供应商](../../../server/video_api.py) · [积分规则](../../../ARCHITECTURE.md) |

这一方案需要同时保存两组时间。**源时间**回答“店主在原片哪一刻说了这句话”，以原片时间码或毫秒表示。**成片时间**回答“商品和这句字幕在交付文件的哪一帧出现”，以 Trupic 的 24 fps 帧号表示。对 15 秒片，最后一镜的结束边界是第 360 帧（不含）。淡化转场和补片尾占用的帧必须计入总数。口播长于分镜时先调整词句，原声切片则改选完整区间。这样可以避免为了凑订单时长把一句话的限制条件剪掉。

## 6. 已运行的验证

第一阶段已接入营销助理。下表中的系统朗读样片保留为早期对照。当前实现使用同一张抹茶商品图，从上传、逐镜审稿、确认积分到交付均经过 Trupic 原有接口，成片另附独立人声、字幕和可编辑工程。[商家交付实录与成片](./merchant-demo/README.md)

| 验证 | 实际结果 | 对集成的影响 |
| --- | --- | --- |
| ClipForge 原版镜像，禁网、无密钥、关闭 TTS 与 BGM。一张合成测试图，导入两句脚本 | HTTP 全程跑通。首镜绑定商品图、次镜回退到同一张图，产出 H.264 720×1280。分镜原计划共 4 秒，转场后文件和时间线均为 3.5 秒 | 单图可以真实交付视频。转场也会改变时长，须按编码结果验收 |
| Trupic 示例商品图 + ClipForge 原始字幕时间线函数 + 本机中文朗读 | [样片](./matcha-15s.mp4)全程使用仓库自带的[同一张抹茶图](../../../server/scenes/matcha.webp)。三镜分别为 0–3、3–10、10–15 秒。三段口播实测 1.88、4.47、3.52 秒。六张字幕按短句切换。文件为 720×1280、H.264/AAC、15.000 秒、360 帧，综合响度 −16.1 LUFS。ClipForge 八项技术质检均为通过 | 保留固定镜头边界也能配音。该片使用句级估时、示例台词和本地音色，未经过线上商家、报价或发布流程 |
| ClipForge 质检应用到两条 Trupic 九秒历史验收片 | 两条均有声音，无检出的黑帧、冻结或长静音。综合响度均为 −31.7 LUFS，上游默认低于 −30 判失败 | 先按人声片和氛围配乐片分别观察响度，避免把轻配乐片误拦。参考[上游默认阈值][cf-qc] |
| OpenMontage 原始 FFmpeg 工具按三段时间重剪 Trupic 咖啡样片 | 输入 9.000 秒、24 fps。输出约 9.021 秒、30 fps，720×1280。上游抽取四帧，报告通过，未比对台词 | 可用素材编号与剪辑指令驱动本地渲染。Trupic 需独立验收帧率、商品和口播。[渲染实现][om-render] |
| AutoClip 原始切片器和选段测试 | 合成源片为 25 fps。截取 1.400–4.200 秒后得到 70 帧、画面 2.800 秒、H.264/AAC。5 项选段测试通过，选段测试使用模拟模型 | 源区间可追溯。成片需转换帧率，并另用真实中文商家视频评估候选是否值得发布。[切片器][ac-cut] · [选段测试][ac-tests] |
| Trupic 现有生产回归 | 隔离数据库、本地 FFmpeg 和测试文案模型下真实导出 15、30、45 秒，对应 360、720、1080 帧。参考片授权隔离和切点用例通过 | 新能力可直接沿用这组验收基线。[回归用例](../../../tests/test_workflows.py) |

这些验证覆盖本机的素材、时间、编码和部分审核。真实云模型的商品一致性、长中文直播挑片质量、普通商家的发布意愿和单条实耗仍需用内测素材测量。

## 7. 实施顺序与上线判断

1. **先做“发一张商品图，得到 15 秒带货片”。** 首版复用商家素材、现有文案模型和分镜，在视频任务中加入逐镜音频、短句字幕和开声试听，作品仍可静音阅读。用饮品、带小字包装的零售商品、带型号的数码商品各做样片，与现有配乐版盲比。优先看商家能否认出同一 SKU、听清卖点、读全活动条件，以及愿意直接发布哪版。硬性回归为 360 帧、口播不截断、同一确认请求只扣一次。
2. **再做“补一段实拍，只换这一镜”。** 让商家上传有成片使用权的短素材，Web 作品页先支持替换镜头、锁定其他镜头与保留旧版。用一段倒茶实拍和一段相机操作实拍测试。验收时对照未改镜头的素材哈希、外部任务号、供应商用量和积分流水。由此再做仅换开场的 A/B 版本，保留可比较的共同部分。
3. **有长素材的商家试点“从原话剪精华”。** 先把候选、理由、原片时间码与试听做成一张选择卡，再接成片与发布包。请店主独立挑选同一原片的可发布段，记录系统前几条候选的采纳数、切断条件句的次数、每小时素材处理时间和实际成本。有这些数据再确定每次给几条、要不要独立定价，以及是否扩大到更多行业。

**部署与许可证会影响复用方式。** ClipForge 和 OpenMontage 都是 AGPLv3，ClipForge 标识为 AGPL-3.0-only。直接并入上游实现、修改后供用户经网络使用或再分发，要依据具体交付方式审查对应源码与版权声明义务。放在独立进程中也要做同样判断。建议首期把两者作为内部对照，按 Trupic 的现有代码实现商品镜头规则与固定时长交付。AutoClip 为 MIT，可选用其挑片或切片模块并保留版权及许可声明，另核对所用模型、素材与依赖的授权。[ClipForge 许可证][cf-license] · [OpenMontage 许可证][om-license] · [AutoClip 许可证][ac-license]

**“本地合成”也要按数据流理解。** 上述单图成片测试可以禁网。ClipForge 的 Edge 配音会发送台词，云图生图会发送参考图，公共图库会查询外部服务。OpenMontage 的本地 FFmpeg 重剪不需要云，生成新画面则取决于所选工具。AutoClip 使用云转写、云语义分析或云视觉时，分别涉及音频、转写文本或抽帧。接入时由 Trupic 按商家授权选择供应商和用途，商家媒体仅通过所属任务访问。ClipForge 的项目列表直接查询实例中的项目。AutoClip 可以指定独立数据目录。商家登录、素材归属、签名报价和结算应留在 Trupic。[Edge 配音][cf-tts] · [ClipForge 项目列表][cf-projects] · [OpenMontage 提供方][om-providers] · [AutoClip 本地运行][ac-cli]

[cf]: https://github.com/xixihhhh/clipforge/tree/bded6ceaa46649068e8da5882d7c29fd8c977a3b
[cf-analyze]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/app/api/llm/script/route.ts#L156-L173
[cf-prompt]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/lib/script-engine/prompts.ts#L628-L655
[cf-motion]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/lib/script-engine/prompts.ts#L268-L285
[cf-stock]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/app/api/project/%5Bid%5D/stock-fill/route.ts#L149-L156
[cf-select]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/app/api/project/%5Bid%5D/compose/route.ts#L355-L380
[cf-open]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/lib/publish-readiness.ts#L153-L186
[cf-timeline]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/lib/video-composer/timeline.ts#L88-L147
[cf-compose]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/app/api/project/%5Bid%5D/compose/route.ts#L316-L425
[cf-import]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/lib/script-import.ts#L63-L81
[cf-assets]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/app/api/project/%5Bid%5D/assets/route.ts#L38-L89
[cf-lock]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/app/api/project/%5Bid%5D/reference-cuts/route.ts#L73-L125
[cf-qc]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/lib/video-composer/qc.ts#L65-L79
[cf-license]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/LICENSE#L540-L551
[cf-tts]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/lib/edge-tts.ts#L198-L231
[cf-projects]: https://github.com/xixihhhh/clipforge/blob/bded6ceaa46649068e8da5882d7c29fd8c977a3b/src/app/api/project/route.ts#L6-L11
[om]: https://github.com/OpenMontageInc/OpenMontage/tree/2e003e65fa99a0f329478a2c1cdcf26bc481933a
[om-arch]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/PROJECT_CONTEXT.md#L7-L57
[om-scene]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/schemas/artifacts/scene_plan.schema.json
[om-assets]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/schemas/artifacts/asset_manifest.schema.json
[om-edit]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/schemas/artifacts/edit_decisions.schema.json
[om-product]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/skills/creative/commercial-product-video.md#L13-L104
[om-backlot]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/backlot/README.md#L3-L31
[om-render]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/tools/video/video_compose.py#L1944-L2002
[om-license]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/LICENSE
[om-providers]: https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/README.md#supported-providers
[ac]: https://github.com/zhouxiaoka/autoclip/tree/559f01900aed62ca8bc9244d7bd7092ab29bd82e
[ac-find]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/backend/pipeline/clip_finder.py#L229-L315
[ac-run]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/backend/services/simple_pipeline_adapter.py#L540-L590
[ac-cli]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/docs/CLI_AND_MCP.md#L18-L71
[ac-duration]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/backend/pipeline/clip_finder.py#L45-L55
[ac-frame]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/backend/services/studio/framing.py#L1-L21
[ac-cut]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/backend/utils/video_processor.py#L129-L207
[ac-tests]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/backend/tests/test_clip_finder.py
[ac-license]: https://github.com/zhouxiaoka/autoclip/blob/559f01900aed62ca8bc9244d7bd7092ab29bd82e/LICENSE
