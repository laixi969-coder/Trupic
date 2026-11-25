# V4 微信小程序核对记录

2026-11-25 核对本仓库 main 提交 35ba67b。产品范围以用户的《商家智能营销创作平台 PRD V4.0 Personal Agent》、原生代码和本地验收记录为准。公开搜索未找到能证明生产版已发布的产品页。

- `miniprogram/pages/home/home.wxml` 首屏通过「进入我的对话」进入助理。
- `miniprogram/pages/agent/agent.wxml` 有文字框、添加照片和发送，有选稿、制作报价与成品操作。
- `src/PersonalAgent.jsx` 使用浏览器中文听写。原生端的同一入口尚缺，PRD 写明了「可结合语音转文字」。
- 验收账号的面包房案例先选第二组，再确认 4 积分，交付海报和推广文案。该数值只代表这一笔测试报价。
- 三份页面为设计初稿，使用本地样例。语音转写调用当前浏览器支持的听写服务；写回当前草稿后由用户发送。微信真机录音仍待原生端接入及真机验证。

[项目源代码](https://github.com/laixi969-coder/Trupic/tree/35ba67b9dee065c8f2b9290a6bf02bdd4c271b39/miniprogram)
