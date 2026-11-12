# EgoLens · 拾迹

**点击物体，追溯事件，用可回放的视频与语音证据回答问题。**

EgoLens 是一个第一人称视频记忆助手原型：SAM2 接收用户点选并追踪目标；Qwen2.5-VL 查看场景和目标局部；混合检索、多轮记忆与有界反馈组织问题；DeepSeek 根据视频和时间对齐的语音证据回答，保留可回放来源。

- 项目主页：[egolens.top](https://egolens.top/)。
- 预录示例：`site/assets/demos/`，包括多轮对话、定向证据补看、语音来源回放，以及补充追踪片段；问答取自真实历史记录，不冒充现场推理。

## 目录

```text
src/egolens/
  core/       证据约束、检索、反馈、会话状态与记忆
  vision/     原生Qwen视频接口、显式目标局部证据
  audio/      时间戳语音证据、可选VAD/ASR准备
  services/   Qwen与SAM2独立推理进程
  web/        Web API及点击追踪工作台
  settings.py 统一外部配置
  cli.py      准备数据、检查、启停和网页预览入口
site/         论文式项目页、预录视频和素材说明
requirements/ 按服务拆分的依赖列表
docs/         环境、数据和部署说明
```

公开仓库只包含运行主线、配置示例、环境说明、网页和少量演示媒体/经筛选的历史问答内容。模型权重、完整数据集、实验脚本、测试报告、缓存和运行中的会话均不随仓库发布。

## 1. 配置环境与模型

以Linux作为推理部署环境。先阅读[环境列表](docs/ENVIRONMENTS.md)，为API、视觉、追踪分别准备环境；按自己的GPU/CUDA安装PyTorch，并自行安装官方SAM2源码和下载模型。环境之间通过本机HTTP通信，不要求使用特定GPU编号。

```bash
git clone https://github.com/heiheiheiha00/egolens.git
cd egolens
cp config.example.json config.local.json
cp .env.example .env
```

在`config.local.json`填写：Qwen模型目录、SAM2权重、环境Python路径、GPU编号、允许访问的视频根目录、记忆索引及语音文件。可选ASR需要另外填写Whisper和Silero权重。`.env`中填写自己的`DEEPSEEK_API_KEY`，可另外设置私人工作台访问密码`DEMO_ACCESS_TOKEN`。这两个文件已被Git忽略。

在各环境安装本项目（或使用`PYTHONPATH=src`）：

```bash
/path/to/api/python -m pip install -e . --no-deps
/path/to/visual/python -m pip install -e . --no-deps
/path/to/tracker/python -m pip install -e . --no-deps
/path/to/api/python -m egolens doctor
```

`doctor`只检查配置，不启动模型。示例中的路径和GPU由使用者决定；没有内置实验室路径或自动下载模型。

## 2. 准备自己的视频

先只启动视觉服务，将视频放在`media_roots`允许的目录下，再建立用于检索的分段导航索引：

```bash
/path/to/api/python -m egolens start --services visual
/path/to/api/python -m egolens status
/path/to/api/python -m egolens ingest data/videos/example.mp4 \
  --day DAY1 --start 12000000 --title "我的示例视频"
```

视觉服务准备就绪后再执行`ingest`。可使用已有的索引和语音文本，格式见[数据说明](docs/DATA.md)。使用`--transcribe`会调用用户指定的音频环境，运行Silero VAD与Whisper；不会训练模型。

## 3. 点击、提问与回放

在工作台选择视频 → 固定当前帧 → 正点/框选 → 确认并追踪 → 提问 → 点击证据回放。选错时补正点/负点，确认新版本；不同目标使用独立编号。长视频单次追踪一个约60秒区间，5FPS；缺失或重现候选不会被当作已确认物理身份。当前查询限定所选视频。

## 已知边界

小目标类别识别、长遮挡重现、相似物体身份与长窗口证据冲突仍可能出错。摘要用于导航，模型回答不是人工核验事实。预录短片只展示组件，不证明完整视频或整周追踪能力；本仓库不附测试脚本，也不将开发成绩当作独立论文基准。

项目页发布见[部署说明](docs/DEPLOYMENT.md)。第三方代码、模型和演示素材的许可分别见[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目原始代码的统一发布许可证待作者确定；不要将第三方许可合并标成一个项目许可证。

## 基础工作

- [EgoLife / EgoRAG](https://github.com/EvolvingLMMs-Lab/EgoLife)，CVPR 2025。
- [SAM2](https://github.com/facebookresearch/sam2)，使用SAM2.1 Small权重。
- [Qwen2.5-VL](https://github.com/QwenLM/Qwen2.5-VL)。
- [Whisper](https://github.com/openai/whisper)、[Silero VAD](https://github.com/snakers4/silero-vad)、[OpenCLIP](https://github.com/mlfoundations/open_clip)。
