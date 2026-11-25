# Trupic V4 升级基线

盘点日期为 2026-11-25。升级从 main 的 c12e8594c7d2d5a30f5fa7eea83f6a0c8da3ca28 和当时的工作区继续。已提交基线可由本地标签 `baseline/pre-personal-agent-c12e859` 定位。本机升级前同时留存了含未提交源码的私有归档及通过 SQLite 在线备份 API 生成的数据库快照，数据库完整性检查返回 `ok`。两者保存在忽略版本控制的 `.trupic/backups/personal-agent-v4-pr4zq0mk/` 下。媒体、模型权重和签名文件仍由现有数据卷管理，数据库快照单独使用无法恢复媒体。

| 能力 | 基线路径和依赖 | 已有证据与边界 |
| --- | --- | --- |
| 商家网页和运营后台 | `src/main.jsx`、`src/AutoCreate.jsx`、`src/Admin.jsx`，React 19、Vite 7 | 原网址哈希、作品详情、商家档案、后台权限沿用。升级前没有持久化商家对话。 |
| 移动端 | `miniprogram/pages/`、`miniprogram/lib/api.js`，原生微信 API | 原有 10 页，包括朋友圈、图文快创、短片、套餐、邀请和作品。回归入口为 `tests/miniprogram.cjs`。 |
| 创意总控和文案 | `server/auto_creation.py`、`prompt_agent.py`、`creative.py`、`copy_choices.py`、`wenan.py` | 签名方案、创意构思、模型写稿、独立选稿审核、商家定稿及与各成品共用的文案。 |
| Skill、案例与知识 | `.agents/skills/` 六个项目 Skill 目录，`trupic-creative-library/references/catalog.json` schemaVersion 1，`server/skill_library.py`、`governance.py` | 目录列有 6 个 integrated、9 个 workflow、10 个 reserve。另有数据库上传和灰度版本。固定用例覆盖禁用依赖、试验、发布与回退。 |
| 海报、素材与保真 | `server/media.py`、`reference_assets.py`、`poster_composition.py`、`region_edit.py`、`visual_review.py`，Pillow、内置字库、可选抠图与视觉模型 | 主体、配色、构图、选区修改、像素检测、导出复核经存量图像回归。真实供应商质量取决于连接和样本。 |
| 视频开场与剪辑 | `server/campaign.py`、`shot_detail.py`、`film_timing.py`、`film_edit.py`、`video_api.py`，FFmpeg、ffprobe | 仓库可核实的实现是 video_storyboard 1.1.0、首镜观察、不同片长的开场和结尾、实物细节与逐帧校验。第一个镜头覆盖前两秒。没有发现独立命名的“前两秒”插件或历史留存率数据。 |
| 模型与成本 | `server/model.py`、`providers.py`、`model_tools.py`、`model_admission.py`、`costs.py` | 文字、图片、图像编辑、视频和视觉审核分能力路由。目录同步、主备切换、连接实测、熔断及账单归集有回归用例。 |
| 队列和交付 | `server/app.py`、`auto_pipeline.py`、`store.py`、`work_history.py`、`object_storage.py`，Flask、Waitress、SQLite、本机文件、可选 COS | 原系统持久化 job、creative_run、work、version，启动可恢复，失败释放积分，作品链接按商家校验。 |
| 商业与权限 | `wallet.py`、`pricing.py`、`commerce.py`、`growth.py`、`coupons.py`、`staff.py` | 批次钱包、签名支付桥、渠道归属、奖励、冲回、优惠券、财务和客服授权均走现有接口。支付回归使用隔离凭证。 |
| 定时服务与部署 | `server/app.py:start`、`topics.py`、`event_sources.py`、`scripts/dev.mjs`、`.env.example` | 周主题、事件同步、订单及权益处理、失联作业恢复、对象同步在原服务运行。单主机部署，多进程共享工作队列尚需另行设计。 |

基线全量 Python 回归为 127 项通过。已有仓库记录未提供可比较的真实商家盲评分、获客转化、全量成功率或生产成本分布。升级验证与外部待验项见 [验收进度](PRD-验收进度.md)。
