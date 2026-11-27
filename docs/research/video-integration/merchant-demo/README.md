# 抹茶拿铁商家交付实录

[播放从上传商品图到收片的网页实录](./journey.mp4) · [播放一张图生成的轻快口播短片](./expressive/generated/film.mp4) · [听同一句话的音色对照](./voice-comparison/same-line.mp3) · [试听顺序与语气说明](./voice-comparison/README.md)

网页实录约 43 秒，压缩了模型处理的等待时间。第 27.33 秒起，网页正常速度播放本次实际下载的 15 秒 Vivian 轻快版成片。

商家上传一张抹茶拿铁图，要求介绍杯壁上的分层、邀请顾客到店，语气轻快，像店员递上一杯饮料。营销助理用本机 Qwen 模型看图、起草并复核，商家在网页看到的三句是「瞧瞧杯壁。」「你看，抹茶和牛奶分层清晰。」「来店里点一杯。」点击确认后，Qwen3-TTS 用 Vivian 音色和轻快语气配音。交付的 MP4 为 720 × 1280、24 fps、15 秒，包含 360 帧及 AAC 混音。[报价页截图](./expressive/generated/quote.png) · [交付页截图](./expressive/generated/delivery.png) · [三镜画面](./expressive/generated/frames.jpg) · [剪辑包](./expressive/generated/edit.zip)

| 商家输入 | 实际配音 | 成片和声音 | 复核记录 |
| --- | --- | --- | --- |
| 一张图和一条需求，要求轻快语气 | Qwen3-TTS Vivian，轻快 | [成片](./expressive/generated/film.mp4) · [独立旁白](./expressive/generated/voice.wav) · [发布文案](./expressive/generated/post.txt) | [审核、字幕和积分](./expressive/generated/checks.json) |
| 三行商家定稿，框出杯壁纹路 | Qwen3-TTS Vivian，亲切 | [成片](./expressive/film.mp4) · [同稿独立旁白](./expressive/voice.wav) · [剪辑包](./expressive/edit.zip) | [确认积分](./expressive/quote.png) · [最终交付](./expressive/delivery.png) · [审核记录](./expressive/checks.json) |
| 同一份三行商家定稿，框选相同区域 | Kokoro，中文预置音色 59 | [成片](./film.mp4) · [同稿独立旁白](./voice.wav) · [剪辑包](./edit.zip) | [确认积分](./quote.png) · [最终交付](./delivery.png) · [审核记录](./checks.json) |
| 同一条轻快口播需求，由本机模型写稿 | Kokoro，中文预置音色 59，使用固定语气 | [成片](./generated/film.mp4) · [独立旁白](./generated/voice.wav) · [剪辑包](./generated/edit.zip) | [确认积分](./generated/quote.png) · [最终交付](./generated/delivery.png) · [审核记录](./generated/checks.json) |

四次演示各自使用临时商家账户和同一张仓库示例图。报价前后可用余额均为 120 积分，确认时预占 12，交付后余额为 108。重放网页发出的确认请求后，任务编号相同，积分流水只有一笔消费。每套剪辑包保存净画面、独立旁白、压低的配乐、最终混音、可编辑字幕和逐帧时间线。[上传后保存的原图](./original.png) · [轻快版逐句字幕](./expressive/generated/captions.srt) · [轻快版时间线](./expressive/generated/timeline.json)

检查记录中的 `independentTranscript` 是 Whisper 从最终视频混音重新听写的结果。它把轻快版的「杯壁」写成同音的「卑鄙」，而成片字幕保留了确认的原稿。可直接播放独立旁白判断发音和表现力。[轻快版旁白](./expressive/generated/voice.wav)

## 本机复验

需要项目的 Python 环境、FFmpeg 和 ffprobe。macOS Apple Silicon 可通过 `.venv/bin/python -m server.film_voice --prepare-qwen` 准备 Qwen3-TTS。Kokoro 可通过 `.venv/bin/python -m server.film_voice --prepare` 准备。让助理自行写稿时，在另一个终端执行 `npm run vision:serve`，或复用已在本机 7395 端口提供服务的同一 Qwen 模型。

在项目根目录运行。示例命令在网页中点击「确认制作」并截图。省略 `--chrome` 后，脚本调用相同的确认接口。每次检查全部通过后才保存当前结果。

```sh
npm run build
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
output="docs/research/video-integration/merchant-demo"
TRUPIC_FILM_VOICE_ENGINE=qwen3-mlx .venv/bin/python scripts/proof-product-film.py --generated --chrome "$chrome" --out "$output/expressive/generated"
TRUPIC_FILM_VOICE_ENGINE=qwen3-mlx .venv/bin/python scripts/proof-product-film.py --chrome "$chrome" --out "$output/expressive"
TRUPIC_FILM_VOICE_ENGINE=kokoro .venv/bin/python scripts/proof-product-film.py --generated --chrome "$chrome" --out "$output/generated"
TRUPIC_FILM_VOICE_ENGINE=kokoro .venv/bin/python scripts/proof-product-film.py --chrome "$chrome" --out "$output"
```

验收涵盖实际素材上传、方案和积分确认、生产任务、重复确认、预占和结算、字幕下载、原图保护区、分镜时间边界、音视频规格，以及最终 AAC 中的人声与独立旁白的相关性。商家账户数据随隔离服务退出而清理。[复验脚本](../../../../scripts/proof-product-film.py)
