# 私有视频与索引

原始视频、导航索引和语音文件放在用户自选位置，默认`data/`被Git忽略；不上传个人视频、会话或模型权重。

## 推荐：自动准备

配置`media_roots`后，先启动Visual服务，再运行：

```bash
egolens ingest data/videos/example.mp4 --day DAY1 --start 12000000 --segment-seconds 30
```

`DAY1`表示记录日的相对编号。`12000000`表示12:00:00、帧号00（8位HHMMSSFF，语义时间以30FPS解释）。每段导航记录保留原视频偏移，不把切段后的0秒误当原视频0秒。用自己的长视频时可选更短的导航段；摘要本身不是事实证据，回答仍会查看原画面。

## memory_file示例

```json
[
  {
    "date": "DAY1",
    "start_time": "12000000",
    "end_time": "12003000",
    "text": "A person holds a yellow tool near a desk. Navigation only; verify in video.",
    "global_overview": "A room and a desk, with a handheld tool.",
    "video_path": "data/videos/example.mp4",
    "clip_id": "example_000000",
    "duration": 30.0,
    "media_offset": 0.0,
    "title": "我的示例视频"
  }
]
```

一个长视频对应多条记录，每条保留同一`video_path`、各自`media_offset`以及不重复`clip_id`。路径应位于允许的视频根目录，加载时检查文件存在和范围。

## audio_memory示例

```json
[
  {
    "clip_id": "example",
    "video": "data/videos/example.mp4",
    "clip_start_seconds": 43200,
    "segments": [{"start": 3.2, "end": 4.8, "text": "这个还没有装回去"}],
    "source": "user-transcript",
    "alignment": "source-media-seconds"
  }
]
```

这里`clip_id`须等于原视频文件名去掉扩展名。语音起止秒是原视频中的秒数；`clip_start_seconds`是录制起点在当天的秒数。语音证据与可见事实分开，谈到维修不等于画面证明维修完成。

使用`egolens ingest ... --transcribe`可生成VAD/ASR文本；ASR会出错，不能推断未确认的说话者身份。替换视频后应重新准备索引和语音；启用源签名的旧证据不会在视频改变后继续复用。更新索引后重启Web服务以刷新视频列表。
