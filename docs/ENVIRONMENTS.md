# 环境列表与用户配置

推荐按进程隔离，避免为SAM2升级依赖时破坏视觉或检索环境。环境目录、模型路径及GPU编号全部由`config.local.json`指定。

| 环境 | 职责 | 已验证的关键版本参考 |
|---|---|---|
| API / 检索 | FastAPI、OpenCLIP CPU嵌入、检索与会话 | Python3.10.18；Torch2.1.2、TorchVision0.16.2、OpenCLIP2.29.0、NumPy1.26.4；FastAPI0.162.2、Uvicorn0.54.0、Pydantic2.14.3 |
| Visual | 原生Qwen2.5-VL推理 | Python3.12.13；Torch2.13.0、Transformers4.54.0、Accelerate1.14.0、Decord0.6.0、NumPy1.26.4 |
| Tracker | SAM2.1 Small视频分割 | Python3.10.18；Torch2.5.1+cu121、TorchVision0.20.1+cu121；官方SAM2源码、NumPy1.26.4 |
| Audio，可选 | 离线VAD/ASR | OpenAI Whisper20250625；官方Silero VAD工具和用户提供的JIT权重 |

这是开发服务器上的已运行版本参考，不表示所有新GPU都能直接使用相同CUDA轮子。特别是较新GPU，需要选择支持其架构的PyTorch/CUDA版本后再验证；本仓库不复制原服务器环境。

## 安装顺序

1. 系统安装FFmpeg/FFprobe、NVIDIA驱动和Python。确认`nvidia-smi`可用。
2. 为三个服务建立各自环境，例如`.venvs/api`、`.venvs/visual`、`.venvs/tracker`。
3. 根据GPU和CUDA，在各环境安装兼容的Torch/TorchVision；API可用CPU版本。
4. 安装对应的`requirements/api.txt`、`visual.txt`、`tracker.txt`。按[SAM2官方说明](https://github.com/facebookresearch/sam2#installation)安装其源码；SAM2不随本仓库打包。
5. 各环境运行`python -m pip install -e . --no-deps`，填写配置，再运行`egolens doctor`。
6. 如需从原视频生成语音文本，准备Audio环境，安装`requirements/audio.txt`和合适的Torch，填写Whisper/Silero本地权重路径。

## 必需的外部资源

- Qwen2.5-VL模型目录：`model_path`，默认逻辑按7B规模设计。
- SAM2.1 Small checkpoint：`sam2_checkpoint`；Hydra模型配置：`sam2_model_config`。
- OpenCLIP文本嵌入：模型名与checkpoint可使用官方预训练标识或本地文件路径。首次使用标识可能下载资源；离线机器请提前配置本地权重和缓存。
- 可选Whisper large-v3及Silero VAD JIT权重；已有时间戳语音文本时不必启动ASR。
- 用户自己的DeepSeek API凭据和模型名称。

单卡32GB以上可以作为合并部署的验证起点，CPU内存建议64GB以上；实际峰值取决于视频、采样窗口和同时运行的模型。原验证曾将视觉与追踪分卡，不承诺任意24GB单卡配置都能同时常驻。通过配置选择空闲GPU即可，不写死设备0或3。
