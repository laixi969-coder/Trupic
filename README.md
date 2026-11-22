# 响指出片 Trupic

面向商家的营销创作工作台。商家可以用一句需求启动创作，添加商品照片，确认方案与积分，然后下载海报、文案或短片。界面支持桌面和手机。

当前功能与原始条款的对应关系见 [PRD 验收进度](PRD-验收进度.md)。

## 启动

当前项目使用 React、Vite、Flask、SQLite、Pillow 和 FFmpeg。在项目目录执行以下命令。需要 Node.js 22.12 或更新版本、npm、uv，以及带 ffprobe 的 FFmpeg。

```sh
npm ci
npm run setup
npm run build
npm start
```

打开 [本地工作台](http://127.0.0.1:7341)。开发模式使用 `npm run dev`，前端默认使用 7341 端口，API 使用 7342。构建模式只需要一个服务进程，可通过 `PORT` 更改端口。

在 macOS 14 及以上版本，安装脚本会用 Swift 编译系统 Vision 主体分割工具。Linux 环境可通过 `TRUPIC_CJK_FONT` 指定简体中文字体。系统无法使用主体分割时，应用保留原图。

## 微信小程序

微信开发者工具导入本仓库根目录。项目配置指向 `miniprogram/`，采用原生 WXML、WXSS 和 JavaScript。底部「创作」从需求、素材和输出规格开始，「灵感」可以按行业筛选并带入样张方向，「我的」可管理商家档案、查看任务和重新打开作品。

- 本地联调先按上文启动服务。开发版默认访问 `http://127.0.0.1:7341`，开发者工具连接本机 HTTP 时，在本地设置中开启“不校验合法域名”。手机访问时使用手机可达的业务服务地址。
- 项目默认使用测试标识 `touristappid`。真机体验和发布使用自己的小程序 AppID，在 `miniprogram/config.js` 填写已部署的 HTTPS 服务地址，并在微信公众平台配置 request、uploadFile 和 downloadFile 合法域名。开发者工具的个人设置保存在被 Git 忽略的 `project.private.config.json`。
- 商家数据由现有 Flask 接口保存。服务使用独立签名会话辨识工作空间，方案确认后按服务返回的积分提交，生成结果支持复制文案或保存图片、短片到相册。
- 小程序流程测试运行 `node --test tests/miniprogram.cjs`。测试模拟微信平台接口，使用独立临时数据库启动真实后端，验证生成和导出。后端回归运行 `.venv/bin/python -m unittest discover -s tests`。

## 商家操作

1. 在「商家档案」填写已确认的经营信息，也可以直接从工作台写下需求。
2. 在工作台选择海报、文案或短片。素材库支持 JPG、PNG 和 WebP。明显模糊、分辨率不足及严重曝光异常的图片会在生成前提示更换。抠图结果可核对并切回原图。
3. 确认创意、推测受众、格式和用量后生成。海报和短片都可在需求框下选择 3:4、1:1、9:16、4:5、16:9，并独立记住各自的画幅和短边分辨率（720、1080、2160 像素）。海报可选 72、150、300 DPI，导出 PNG。短片输出 9 秒、24 fps 的 MP4，含三段字幕画面和配乐；文案可复制或下载 TXT。
4. 作品页可应用预览过的替换标题、换创意或恢复旧版本。任务中断后可在「我的作品」重试。
5. 右上角可查看积分明细。点击头像可将当前工作空间绑定到账号，在其他浏览器登录后继续使用。

新工作空间有 120 体验积分。当前文案 0 分、海报 4 分、短片 12 分。选题、建议替换和换创意免费。成功写入成品与版本时同步结算。以上价格、画幅与时长用于本地体验，后续可按实际业务定价调整。

## 模型与素材

默认配置可离线运行。创意引擎结合原始需求、商家档案、消费场景、近期角度和已启用的策略生成文案，并使用原图或带示意标识的场景图制作成品。素材处理支持清晰度与曝光检测、保守调光、主体分割和摄影背景合成。针对包装或外观还原的请求需要真实商品原图。

管理员可以在「运营管理 → 服务连接」保存以下配置。

| 能力 | 配置 |
| --- | --- |
| 文案模型与复核 | Chat Completions 完整接口地址、模型名称及服务所需密钥。首次调用创作文案，再单独发起事实与表达复核。异常响应或未通过结果回退至本地规则。 |
| 图像生成 | 支持 Images Generations、返回 `data[0].b64_json` 的接口、图像模型及对应密钥。工作台的分层导出仅发送创意描述生成背景或概念配图。商家原图的主体在本地合成。商业海报 agent 的整图入口 `python -m server.qwen_image` 支持百炼 `qwen-image-3.0-pro` 和 `qwen-image-3.0`，可随提示词发送指定商品原图。 |
| 授权参考来源 | RSS / Atom 链接与授权条件，或 Pinterest 画板数字 ID、拥有读取权限的令牌及引用条件。每日发现新条目、去重、记录来源并提出候选方法，供管理员核实。 |
| 本地活动 | 在「本地活动」核对主办方来源、城市和日期。系统根据经营地区和本周日期选取主题。 |

未配置远程文案服务时，应用会检测已由设备所有者启用的 macOS Foundation Models CLI。不可用时，确认页和作品检查记录显示「本地创意规则」。外部服务配置留空即可使用本地模式。对接的服务按其自身条款计费。

运营人员也可使用环境变量配置。环境变量优先于界面设置。

「运营管理 → 模型平台」可分别保存 Atlas Cloud、火山引擎方舟、阿里云百炼、DeepSeek、本机服务及其他兼容平台的连接。每个平台可配置文案和视觉模型 ID。将两项「创作调用平台」分别保存后，创作请求按所选平台使用各自的地址、密钥和模型。选择「服务连接中的默认配置」会恢复原配置及其环境变量。视觉连接验证会用随机色卡实际检查图片输入。今日请求统计按平台、模型和用途展示成功响应、耗时及平台返回的 token 用量，失败请求也会计入请求次数。

方舟可填写账户已开通的模型或推理接入点 ID。百炼可替换成业务空间与地域对应的完整地址。视觉审核所选模型须支持同一请求内的多张 Base64 图片。各平台的 Chat Completions 文档列出适配的模型和输入格式。[Atlas Cloud](https://www.atlascloud.ai/docs/llm-protocols) · [火山方舟](https://docs.volcengine.com/docs/ark/chat-api) · [阿里云百炼](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope) · [DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/)

设置 `TRUPIC_DAILY_TEXT_CALLS` 和 `TRUPIC_DAILY_IMAGE_CALLS` 可分别限制整个服务在 UTC 自然日内发出的模型与图像请求次数。使用非负整数，留空表示不限次数，0 表示只走本地处理。服务在发送请求前计数，超时也占用一次。运营管理的「服务连接」显示当日用量。

```text
TRUPIC_MODEL_URL           TRUPIC_MODEL              TRUPIC_MODEL_KEY
TRUPIC_VISION_URL          TRUPIC_VISION_MODEL       TRUPIC_VISION_KEY
TRUPIC_IMAGE_URL           TRUPIC_IMAGE_MODEL        TRUPIC_IMAGE_KEY
TRUPIC_REFERENCE_FEED      TRUPIC_FEED_LICENSE
TRUPIC_PINTEREST_BOARD     TRUPIC_PINTEREST_TOKEN    TRUPIC_PINTEREST_LICENSE
```

## 商业海报与品牌字

灵感广场提供七张行业样张，每张都能查看镜头、配色与用字，并把构图带入新草稿。示意品牌和价格保留在样张里。需求框下方的「版式与字体」可以切换全幅商品主视觉、杂志编辑、价格主视觉与活动丝印。「商家档案」可保存商用 TTF/OTF 作为默认字体，单次创作也可换字。内置思源黑体、思源宋体与 Barlow Condensed；Hunter 导出的有效字体可直接上传。作品检查记录显示实用字体与缺字回退情况。

[Trupic 商业海报 Skill](.agents/skills/trupic-commercial-poster/SKILL.md) 记录设计与验收方法。[案例拆解](.agents/skills/trupic-commercial-poster/references/visual-study.md) 包含 Pinterest 原始参考和 GitHub 方法取舍。[行业方向](.agents/skills/trupic-commercial-poster/references/directions.json) 由生成服务直接读取，发布项目时须保留此目录。原创概念底图位于 `server/scenes/`，成品示例位于 `public/designs/`。无已配置的外部图像模型时，应用可使用商家原图、匹配的本地场景或文字构图。输出像素与 DPI 可独立设置，实印细节也取决于原始商品图。


## 商品保真与成品审核

网页或小程序选好商品图后，在「核对商品素材」中点选原图上的两个对角，框住必须保持清晰的商标或包装文字。明确要求保真的海报或短片会在预览前检查这片区域。商家确认原图中的内容完整后再生成。

每份新海报都会检查导出的 PNG。九秒短片还会解码全部 216 帧，与对应分镜比对，并对三个镜头各取首、中、尾帧，检查商品区域、文字边界和图文对比度。系统同时核对字幕、交易条件、时长、帧率与音轨。可修复的排版、裁切、偏色或编码问题触发一次重制，使用已确认文案、完整原图和分区排版。只有复检通过的版本才交付并结算。查看作品的「检查记录」，或在「运营管理 → 成品视觉审核」查看初检、重制与拦截记录。

默认在本机检查像素和排版。要评审商品遮挡、图文语义及三镜头推进，可在「服务连接」填写支持图片输入的 Chat Completions 地址、密钥和单独的「成品视觉复核模型」，或设置 `TRUPIC_VISION_MODEL`。启用后，预览会送审原图，交付前会送审原图、海报和短片代表帧。模型未返回有效结论时可重试。可用 `TRUPIC_DAILY_VISION_CALLS` 设置独立调用上限。产品是否与线下实物一致以商家原图和确认为依据。

### 复跑真实视觉验收

本机可通过 llama.cpp 运行 Qwen3-VL。安装含多模态支持的 `llama-server`，将 `Qwen3VL-2B-Instruct-Q4_K_M.gguf` 和 `mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf` 放进 `.trupic/models/Qwen3-VL-2B-Instruct/`，再执行 `npm run vision:serve`。默认监听本机 7395 端口。本机的 Qwen3-VL-2B 逐镜读取实际商品区域，完整原图与成品另做像素比对，通过后再读取整幅海报或三镜并列图写构图观察。作品审核记录将商品结论与画面观察分别保存。[官方模型权重](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF)

在另一终端运行下例，替换商品照片、需求和新建的输出目录。若有保真标识选区，加上 `--region 左 上 右 下`，四个坐标均按原图宽高归一化。

```sh
TRUPIC_MODEL_URL=http://127.0.0.1:7395/v1/chat/completions \
TRUPIC_VISION_MODEL=Qwen3-VL-2B-Instruct \
.venv/bin/python scripts/verify-real-vision.py --photo /path/to/product.jpg \
  --brief '用实拍图介绍这台相机' --output /path/to/new-review
```

脚本在临时数据库中走上传、方案预览、任务、审核和下载流程。它会在首次导出时遮住海报商品，并把短片第二镜置黑。输出目录保存首次导出、复检通过的成品和两轮审核记录。使用云端接口复跑时，图片会发送至选定平台并产生实际模型调用。

## 管理与数据

首次启动会在 `.trupic/admin.key` 生成本机专用管理密钥。打开左侧「运营管理」并使用该密钥登录。可在启动前设置 `TRUPIC_ADMIN_KEY` 来指定密钥。

- 案例库支持优秀、反面及方法分类。入库需记录授权条件和拆解，反面案例需注明具体问题。
- 策略版本可关联已审核的方法。固定测试检查典型业务、版本差异和真实性门槛，记录候选与初始策略结果。支持按商家稳定分组的 10% 灰度、全量启用和回退。
- 运营可抽查作品、查看历史和审核标签，填写来源、统计区间及真实展示、点击、咨询、到店数据。策略页汇总已录入的实际反馈，供版本评估参考。
- 每个商家有独立作品、素材、档案和积分账本。每周准备三个主题，首页展示两个。管理员操作留有审计记录。
- 数据目录默认是 `.trupic/`，可通过 `TRUPIC_DATA` 更改。备份应包含 SQLite 数据库、作品、素材、商家字体和会话密钥。服务默认只监听本机回环地址。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -v
npm run build
```

测试使用临时数据库，覆盖重复提交、余额结算、失败重试、素材真实性提示、商家隔离、成品下载、建议替换、版本恢复、每周选题与运营审核。外部服务需要使用经营方实际授权的账号进行上线联调。

海报和短片的「版式与字体 → 图形文字」支持中英文组合、单语造型字及关闭。行业示意图使用主体蒙版，让大字可以进入前后景。创作文案按商品动作、使用情境和已确认信息选择角度；短片依次呈现近景开场、细节和全景收束，在作品的「成品文案」中可展开九秒分镜。

创作方案生成前，后台会把原始需求、商家资料、素材情况和已选画幅整理成当前媒介所需的指令。确认页可展开「查看优化后的创作指令」，作品页的「检查记录」保留该版本的指令。已连接的文案模型可完成语义策划和指令复核；没有可用模型时使用本地规则。配置入口为「运营管理 → 服务连接」。

商业文案使用项目内的 [hiccai-wenan v4.2.0](.agents/skills/hiccai-wenan/SKILL.md)，固定到[上游提交 643480d](https://github.com/laixi969-coder/hiccai-wenan/tree/643480ded24d513123ec95647ca2aad0f25a767b)。发布时随项目保留整个 Skill 目录。模型写稿和独立复核都会读取原文及当前媒介的参考章节。没有模型时，使用本地实现的促销直述、交易条件保留和按需省略行动号召等规则。作品的「检查记录 → 文案 Skill」记录该版本实际使用的路径。

### 商业海报与短片

在「版式与字体」可选「商品主视觉」「单双色孔版」或「品牌 IP 场景」。孔版示例可输入“蓝墨单色印刷”，或“蓝墨橙墨双色印刷”。前者导出一个墨层，后者导出两个。品牌 IP 需要上传角色参考图。商品主视觉、孔版和 IP 海报在使用对应分层渲染时，可从作品页下载 SVG，编辑文字、替换底图。已分离的商品有独立图层，完整摄影原图以整张照片保存。SVG 使用字体名称，异机编辑需安装对应字体。

新增「食欲定格」「留白光影」「照片编排」。例如「日式美食，居酒屋暗调」「留白光影，突出瓶身反光」「照片编排，保留完整骑行原片」可直接写进需求，也可在网页手选。「灵感广场 → 海报版式」提供对应实排样张。PNG 完成原图和交易信息检查后交付，SVG 保留照片、图框、底色和排字图层。[35 张样本与 Pinterest 拆解](.agents/skills/trupic-commercial-poster/references/poster-reference-review.md)

短片将摄影画面与字幕分开渲染，按开场、细节与收束调整取景。交付前解码导出的 MP4，再检查各镜实际商品及所选标识。运营后台可分别选择文本和视觉平台，查看调用次数、耗时、错误及供应商返回的 token 用量。供应商报价及真实账单另行核对。设计来源及具体取舍见[商业海报视觉研究](.agents/skills/trupic-commercial-poster/references/visual-study.md)。

商品主视觉会结合已确认资料与实物剪影选择构图。摄影器材可用取景投影，原色机身与其型号文字叠放。食材海报可从原图取色，按食材名称和主体轮廓安排前后景。短片作品页的「下载剪辑素材包」包含净画面、逐镜透明字层、可修改字幕 SRT、音轨、CMX 剪点表和镜头说明。三个镜头分别借鉴分层视差、细节慢推和片尾定版。[video-shotcraft 镜头库](https://github.com/Vincentwei1021/video-shotcraft/tree/59f3e9b9e936ff2bce0e18446226d770a3f2f61f/references/shots)

#### 用 Open Design 继续剪辑

新短片优先由 Open Design 同款的 HyperFrames 渲染。`npm ci` 会安装可选的 HyperFrames 运行时。准备 Chrome 时可执行 `npx hyperframes browser ensure`。默认 `TRUPIC_VIDEO_RENDERER=auto`，运行时不可用或渲染失败时改用本地 FFmpeg，仍可交付剪辑工程。可设为 `hyperframes` 要求使用该引擎，或设为 `ffmpeg` 直接使用 FFmpeg。作品的「检查记录」显示实际引擎。MP4 继续走商品保真、文字、音轨和逐帧审核。[Open Design 的 HyperFrames 视频工作流](https://github.com/nexu-io/open-design/tree/e033aad1d15a9d4084316e5223f2c6597fd32619/design-templates/hyperframes)

在网页短片作品页点击「下载 Open Design 剪辑工程」。解压后，在 Open Design 桌面端打开解压目录作为项目，从 `index.html` 进入。镜头时间、画面图层、字幕图层和音轨可单独调整，工程附带源 MP4、逐镜字幕 SVG 和 SRT。成片默认使用已审核的 PNG 字层。修改 SVG 后可将对应字幕轨指向 SVG，预览与导出时需安装相应字体。也可以在解压目录运行 `npx hyperframes@0.9.40 preview`，用 HyperFrames 时间线继续编辑。
