# Trupic 营销助理的下一轮升级

调研日期为 2026 年 11 月 26 日。依据是当前本地工作区、实际交付的抹茶拿铁样片、原有 PRD 验收记录，以及下文逐项列出的上游源码。建议以「商家发出需求后，多久能拿到一份愿意直接发布的成品，改一次需要付出多少」衡量进展。把成功导出、商家采纳、消费者产生行动分别记录。[产品验收范围](../../PRD-验收进度.md) · [本地商家完整实录](video-integration/merchant-demo/README.md)

## 从真实交付看优先级

| 商家遇到的事 | 已有基础 | 下一次升级应交付什么 |
| --- | --- | --- |
| 活动换价，海报、口播、配文都要正确 | 店铺及项目记忆有确认、版本和过期机制，报价会锁定成稿，品牌包已进入创作计划 | 把同款商品和本次优惠绑定到具体版本，自动列出受影响的待发作品。商家确认一次后，只改受影响的内容 |
| 看着都对，交付后才发现小字错了 | 实物区域与原图像素比对、字形对比度、全帧技术复检、可选视觉模型已接入 | 从最终 PNG、MP4 像素读回品名、价格和限制条件，在作品上指出具体错字和位置 |
| 喜欢画面，只想换口吻或收尾 | 有独立人声、配乐、字幕、净画面、版本和签名报价 | 增加「保留画面，换语气」和「只改最后一句」。先看改了什么，再按现有流程报价和交付 |
| 不知道哪版文案更像自己店里的人 | 方法库有固定测试、灰度和回退，真实跨行业盲评仍待开展 | 用真实经营简报盲选成品，记录事实错误、口吻和“我会直接发”三个不同结果 |
| 同一活动发到多个地方，下周还得从头选题 | 商家已有免费周选题、作品下载与修改记录，后台可录入曝光、点击、咨询和到店 | 每次发布关联渠道、作品版本和观察周期，让下次推荐能解释采用了哪一条经营证据 |

### 1. 让每份作品引用同一版商品和活动事实

把现有品牌包里的名称、颜色、Logo、字体继续用于制作。在商家及项目记忆之上增加一张可复用的「商品与活动资料卡」。第一次上传只收这次用得到的信息。以后助理看到「还是上周那杯，把周五到店价改成 19.9」时，能展示匹配到的商品、旧价、新价和有效期，确认后再给出受影响作品的报价。原定稿、已交付版本和旧价对应的时间段保留。到店服务类商家用服务项目和适用门店，无须填写库存型号。[记忆的选择和修订](../../server/context_memory.py) · [已有品牌包](../../server/product_bundle.py) · [方案锁定与计价](../../server/auto_creation.py)

可借用 Schema.org 的 `ProductGroup / Product / Offer` 关系，映射规格、币种、价格、截止日。Trupic 自己保存商家确认人、原话、原图或框选区域、适用门店及活动版本。图上可见的分层能作为镜头依据，奶源、口味和促销需有商家资料。如果商家自己的商品页已输出结构化数据，可作为待确认输入。首版做字段映射即可，运行时无需引入商品管理系统。Schema.org 公布的词汇采用 CC BY-SA 3.0。[GitHub 固定版本](https://github.com/schemaorg/schemaorg/tree/aded30e411c7d4b8fc230145970456e27001c901) · [商品规格关系](https://schema.org/ProductGroup) · [促销字段](https://schema.org/Offer) · [词汇条款](https://schema.org/docs/terms.html)

验收用一店两种规格、同品两店不同价、到期优惠和无促销服务各跑一遍。海报、配文、口播和字幕逐项核对绑定的版本。资料充分时直接给确认卡，价格冲突时只问有分歧的那一项。

### 2. 让换声音和改一句话真正省时间

本次用同一需求交付的 Kokoro 和 Vivian 两个剪辑包做了复用实验。两个包的 `picture.mp4` 和三个固定标题层分别逐字节相同。我取 Kokoro 包的净画面与标题，用 Vivian 包中的实际字幕层、出入帧和混音，调用现有 `render_master`。同一台机器三次耗时 **0.914、0.940、0.837 秒**。新 MP4 与 Vivian 正式交付件逐字节相同，都是 15.000 秒。计时只包含最后一次 FFmpeg 合成，未计语音生成、资格检查、排队、质量审核及下载；也没有测过线上并发。[Kokoro 输入包](video-integration/merchant-demo/generated/edit.zip) · [Vivian 对照包](video-integration/merchant-demo/expressive/generated/edit.zip) · [现有合成入口](../../server/film_edit.py)

先按改动类型决定制作范围。换语气复用净画面和商品区域，重新生成声音、字幕时码和压低后的配乐。只改结尾时，以镜头为单位保留前两段声音，重新检查促销限制是否跨镜出现。换包装或规格应使相关素材、事实和审核结果失效。复用键至少包含租户、输入素材摘要、定稿、模型及音色版本、画幅或相关制作参数。可复用资产原子落盘，重复确认仍使用既有请求键，积分由现有报价与结算事务决定。相同缓存键不能替另一商家取得素材。[文案检查点与任务恢复](../../server/app.py) · [逐镜配音、时码和混音](../../server/film_voice.py) · [现有修改报价](../../server/revisions.py)

这里近期收益最大的实现是复用 Trupic 已有剪辑包。固定时间线继续用现有 24 fps 格式。等商家确实需要在外部剪辑软件往返调整，才试 OpenTimelineIO 的 Clip、Track、媒体引用与适配器。在样例里验证入出点、看得见的字幕和音轨，以及目标软件的实际导入效果。OTIO 自身描述剪辑关系，媒体文件仍须交付。[OpenTimelineIO 源码与格式边界，Apache-2.0](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/36e8d4c8fd5d55f0e0aefea07bc1e626ea3a2794/README.md)

### 3. 用商家愿意发的成品评估提示词和模型

现有规则测试覆盖台球、火锅、茶饮等需求，保真评估脚本也能按人工标注计算结果。下一步把「写得准确」和「写得值得发」各自测出来。建议先收集 **36 条授权简报**，覆盖餐饮、包装零售、到店服务，每类 12 条，包含错价诱因、无促销、品牌禁用词、商品细节不足和改稿。训练示例与留出验收集按商家或商品划分，避免同一件商品同时出现在示例和盲评里。每条先比当前方案和一个候选，一次只改模型、写法或读法中的一项。[既有规则测试](../../server/governance.py) · [保真评估入口](../../scripts/evaluate-fidelity.py) · [真实样本要求](../../外部验收资料清单.md)

Promptfoo 的 Python provider 可包装 Trupic 自己的写稿及复核函数，Python 断言可读实际输出，核对价格与限制、禁用声明、可片内读完的时长、重复开场及每份通过稿的调用成本。先在开发机或 CI 使用其 MIT 核心，正式商家接口延用原路由。对图片、声音和“能否直接发布”，打乱 A/B 顺序给店主判断并允许两版都退回，保留原话。首轮可用简单表单；需要多人复审时再用 Label Studio 社区版的成对比较模板。两者在本次均完成源码核对，尚未接入 Trupic。[Promptfoo Python provider](https://github.com/promptfoo/promptfoo/blob/485074451bd3c77a0abf000bc9a960499a86f286/site/docs/providers/python.md) · [自定义判断](https://github.com/promptfoo/promptfoo/blob/485074451bd3c77a0abf000bc9a960499a86f286/src/assertions/python.ts) · [Label Studio 成对评价，社区版 Apache-2.0](https://github.com/HumanSignal/label-studio/blob/d691e513c3ba2f2919b7326def2222495e0db0ab/docs/source/templates/pairwise_comparison.md)

在本轮抹茶自动稿的隔离记录里，文字请求 5 次、成功 4 次，视觉请求 6 次、成功 6 次。这里没有商用账单，也无法仅从次数认定哪次多余。先把写稿、复核、修稿、原图审看、成片复检的阶段、耗时、失败原因和复用命中与任务关联。现有模型用量、任务事件和财务对账足以起步。跨进程或多个渲染节点出现后，可用 OpenTelemetry Python 的父子 span 串起各阶段；span 中记录时长与匿名任务标识，图、台词及密钥留在原权限范围内。[本次调用记录](video-integration/merchant-demo/expressive/generated/checks.json) · [既有用量记录](../../server/model.py) · [OpenTelemetry Python，Apache-2.0](https://github.com/open-telemetry/opentelemetry-python/blob/817f6d212d43d7a775f986b8ddc0251df23ca0d8/opentelemetry-api/src/opentelemetry/trace/__init__.py)

### 4. 直接检查顾客最后看见的价格、条件和实物

用相同版式做了三张图，分别写「到店价 ¥18.90，仅限周五」「到店价 ¥19.90，仅限周五」「到店价 ¥18.90，仅限周六」。以第一张为准，现有字形可见性和实物区域检查在三张图上均未返回问题。macOS 系统 Vision OCR 从像素正确读出了三组差异，也读出了交付短片三镜的字幕。这项实验只覆盖上述两项现有检查。它说明即使文字清晰、实物完整，也值得单独核对字义。[两项现有检查](../../server/visual_review.py) · [逐样本结果](merchant-quality-evidence.json)

我用 RapidOCR 3.10.0 的中文 PP-OCRv5 mobile 检测和识别模型在本机复测上述六张图。它识别出了 18.90 与 19.90、周五与周六，也完整读回了三镜字幕。首次调用约 19.26 秒，日志含下载与加载模型；其余五次各 0.108–0.126 秒，仅供这台机器和这些图片参考。模型对同一人民币符号给出过半角和全角两种结果，比较应归一等价字形并保留币种。建议先在真实海报上并行读取和记录结果，再决定自动拦截阈值。按排版坐标裁出促销、商品名等已知区域，在交付 PNG 上读一次，在 MP4 每条实际字幕的稳定显示区间抽帧。逐字段比对商家确认值，保留数字、小数点、否定词、数量、币种和有效期。发现明确冲突时回到对应图层修复；无法可靠辨认时，给审核者看原图裁片与应有文字。包身原有的小字和商家叠加的活动价分别比对，避免把包装标价误当促销价。RapidOCR 的 Python 接口提供文本、框和置信度；它列出了所选模型的上游来源，中文 PP-OCRv5 mobile 可核对到 Apache-2.0。初期只需在现有 Python 渲染任务加一个读回步骤。[Python 实现](https://github.com/RapidAI/RapidOCR/blob/e1e8eef04b72c89dd5c0ccd6f2a0101493918f30/python/rapidocr/main.py) · [权重与许可](https://github.com/RapidAI/RapidOCR/blob/e1e8eef04b72c89dd5c0ccd6f2a0101493918f30/python/MODEL_LICENSES.md)

有两项较小的视觉改进适合按作品类型开启。

| 问题 | 本次验证 | 建议何时做 |
| --- | --- | --- |
| 窄幅文字在书名号、括号或价格单位中间折行 | 在 32 像素字体、160 像素栏宽下，现有排版把《留在行尾。采用 Unicode 换行机会后，「《春日》礼」可以一起换行。「¥18.90／杯」仍可能拆开 | 在现有字体实测宽度基础上引入 UAX #14，另把钱数和单位设为不可拆分。先用 100 句中英混排和三种画幅回归。上游 Python 绑定采用 Apache-2.0。[换行实现](https://github.com/WeblateOrg/unicode-segmentation-rs/blob/fa3930fe796a47b9db4f2ca54dd062a1038f2c27/src/lib.rs) · [UAX #14](https://unicode.org/reports/tr14/) · [Trupic 排版](../../server/typography.py) |
| 半透明包装换背景后，杯沿出现原背景色 | 在有真实参考值的 240×200 合成图上，即便透明度完全正确，直接复用输入像素的颜色，1,372 个混合边缘像素的平均 RGB 绝对误差仍有 20.53/255。用 PyMatting 同时估计前景色和透明度后为 0.032/255 | 只在商家选择换背景时生成衍生素材，保留原图和实物标识。先用 30 种真实商品、三类背景检查玻璃、反光袋、细边和品牌色。合成图结果不可当成实物通过率。PyMatting 这条路径无模型权重，代码 MIT。[透明度估计](https://github.com/pymatting/pymatting/blob/6d5c4a6bed0e5672abac0bad078e594423ffe4fd/pymatting/alpha/estimate_alpha_cf.py) · [前景色估计](https://github.com/pymatting/pymatting/blob/6d5c4a6bed0e5672abac0bad078e594423ffe4fd/pymatting/foreground/estimate_foreground_ml.py) |

### 5. 让顾客听到像店主说话的声音，看到真正的商品演示

**先试听这家店的一句话。** 建议在确认制作前，用已经定稿的第一句做 2–4 秒试听，提供「温和介绍」「轻快招呼」两种。两版使用同样的响度和同一个声音，商家能单独判断读法。文案提示词负责把书面卖点改成对客人说得出口的话；逐镜朗读指令控制停顿、重音和句尾。保留商家的选中音频与读法，最终制作复用已选录音，记录试听成本和次数，成片继续走签名报价与积分。现有同稿样音能直接听出差别；口吻偏好由店主盲选验证。[同一句三种读法](video-integration/merchant-demo/voice-comparison/same-line.mp3) · [声音与模型实测说明](video-integration/merchant-demo/voice-comparison/README.md)

**再放开店主自己录。** 增加「用我的原声」作为制作素材入口，明确录制内容、用途和可替换的镜头。对已确认的文本，用 Qwen3 ForcedAligner 计算开口、停顿和收尾时码。对原声说了什么，继续用独立转写并支持回听。本机用社区 MLX 四比特版实跑两条干声和一条混音。四句、34 字的两条干声，对齐边界与现有句段记录的最大差为 107 毫秒；这些记录也不是人工逐字真值。把最后一句文字故意换成「今天免费送两杯」，模型仍然为错句返回了时码。这就是需要独立核词的具体原因。模型适合自录原声、重切字幕，已知时码的短句合成可沿用现有结果。[上游对齐实现](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_forced_aligner.py) · [官方模型与 Apache-2.0 许可](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) · [本次量化权重](https://huggingface.co/mlx-community/Qwen3-ForcedAligner-0.6B-4bit/tree/2f652af86ae0c73fe189b9429225c908ce4bf020)

对中文同音误报，可用 pypinyin 给审核排序。保留声调的拼音比对在两条 34 字样音上分别有 3、3 个编辑差异；完全去调后，轻快版差异归零，原转写的错字却还在。价格、品牌、数量、限制和否定词一律保留原值与回听入口，字幕仍取确认稿。例如「到店」和「倒电」拼音相同，只靠拼音无法判定台词正确。此项放在累积误报样例后做。[pypinyin 实现，MIT](https://github.com/mozillazg/python-pinyin/blob/aab5e696eac5c3a92575a18521db28547c1476bb/pypinyin/core.py)

**扩展到实拍时，直接利用商家拍到的动作。** 让商家上传并授权用于成片的一段倒茶视频，助理按 OpenMontage 的逐镜素材表选择倒茶镜头，前后两镜沿用商品原图。对有解说的长视频，参考 AutoClip 取原话、入出点和前后文，商家试听后确认。ClipForge 的单图商品特写、推近和结尾定版已在第一步发挥作用。Trupic 继续持有素材归属、任务、报价、积分和交付入口。ClipForge 与 OpenMontage 采用 AGPLv3，首期用作设计参考，在 Trupic 自有流程实现所需规则；AutoClip 的 MIT 代码可按模块评估，随分发保留许可与版权声明。[三仓库源码、许可与接法](video-integration/README.md) · [OpenMontage 素材表](https://github.com/OpenMontageInc/OpenMontage/blob/2e003e65fa99a0f329478a2c1cdcf26bc481933a/schemas/artifacts/asset_manifest.schema.json)

多段实拍可试 PySceneDetect 提议切点。本机生成的 8 秒对照片在第 2、5 秒切换不同素材，默认自适应算法、内容算法和 FFmpeg 都找到两处。抹茶样片在第 3、10 秒换镜，同商品构图接近，自适应算法只找到第 10 秒，另两种都没有报点。已有分镜的作品直接使用剪辑时间线；对导入的实拍，候选仍需结合声音、动作和商品终态。先用 10 段不同商品的商家授权实拍，检查镜头能否从原片定位和替换，再考虑引入 OpenCV 依赖。[PySceneDetect，BSD-3-Clause](https://github.com/Breakthrough/PySceneDetect/tree/facff3b7c4db4cd30ffcb7cd17a6d3262ebe2ec2)

### 6. 让下周的营销助理知道上周发了什么

Trupic 已有作品效果表、人工录入和曝光加权的点击率。当前效果记录的主键是作品和版本，一版分别发到两个渠道，无法用这一个主键分别保存两次发布。建议从商家作品页的「已经发了」开始，记录店铺、版本、渠道、发布时间和可选的帖子标识。效果关联到具体发布，再记观察周期、数据来源和指标定义。第一次允许手填或导入平台导出表，未知留空，确实为零时记零。同一累计周期重复导入只更新快照，跨周期报告取对应截止值。下载、认可、发布、点击、咨询、到店分别展示。[现有效果表](../../server/store.py#L104) · [后台录入和汇总](../../server/app.py)

只有商家控制落地页、确实需要看引流时，才值得试自托管 Umami 的网站事件；部署需独立服务和数据库。大量线下二维码活动才考虑 Shlink 的短链访问 API，并处理预览请求和机器人。点击可以说明一次访问，成交和到店需订单、核销或商家证据。微信小程序数据限于对应小程序的可得指标；抖音能力需按具体用途核验资质、申请范围和商家授权。首轮试点可以完全通过商家手填或导出完成。[Umami 事件入口，MIT](https://github.com/umami-software/umami/blob/dbb8d606fbd4e99220fb83bcb4abad3e0f97f42a/src/app/api/send/route.ts) · [Shlink 短链 API，MIT](https://github.com/shlinkio/shlink/blob/80599b89ff9b4ae0f9d19e849e6b747a94dde99c/docs/swagger/paths/v1_short-urls.json) · [微信小程序数据说明](https://cloud.tencent.com/document/product/1301/104571) · [抖音开放能力说明](https://developer.open-douyin.com/capacity-center-page/capacity-detail/7448483112163590181)

验收用「同一条视频、两个渠道、两个观察窗口、同一 CSV 连续导入两次」。商家应能追溯每个数字，下一周的助理能说出「你回填的两次咨询来自这条抹茶片」，在数据不足时直接说明样本量。线上发布率和营销提升需要真实商家参与后才能测得。

### 7. 建议排期与上线条件

| 顺序 | 要交付的商家体验 | 进入下一步前怎么验收 |
| --- | --- | --- |
| 第一轮，同时做两条短路径 | 商品与活动确认卡先覆盖品名、规格、价格、有效期、渠道和适用门店，接交付文件读回；视频在制作前可试听一句，改口吻可复用画面 | 用同一商品完整跑「周五 18.90 改 19.90 → 海报和视频都改对 → 只换口吻 → 再交付」。以 50 张海报、10 条短片作首批试点，记录正确样本误拦率和低置信度回看量，人工植入的错价、错单位、错日期均应被指明或进入复核。重复确认及失败重试按既有积分规则核账 |
| 第一轮开始采样，第二轮据此选模型 | 用餐饮、零售、到店服务各 12 条简报盲选。给第一版、修改及放弃各留一个反馈入口 | 带上样本数、回应率和退回原因比较两版，优先改重复出现的问题。新增提示词、模型和音色先过事实检查，再看商家偏好、单件成本与交付时长 |
| 第三轮，小范围商家试用 | 开放店主原声和授权实拍，补多渠道发布记录与下周周选题反馈；中文窄版排版和透明包装按样本发现频次插入 | 用真实手机上传、试听、导出或存相册、发布和回填，完整跑通一个周期。渠道采集只对授权且可稳定取得的数据启用。外部剪辑器导出、短链服务及高成本视频生成按试点需求立项 |

上述批次和样本量是建议的起始规模。首要指标取「明确回应的商家中，第一版就选可直接发的作品占比」，同时公开回应率和各行业分布，避免只看到满意用户。效率记录从上传到首份获认可成品、从发起修改到交付的 P50/P90，拆开商家确认时间与系统作业时间。成本按获认可的成品统计模型调用、实际计费或本机计算时间，并单列重试及试听。同步看事实错误、误拦、重复扣分和无人反馈的作品数。当前有单品局部耗时、样音和技术试验；真实商家采纳率、线上并发和经营收益仍待首轮建立基线。[实验数据与边界](merchant-quality-evidence.json) · [既有外部验收清单](../../外部验收资料清单.md)
