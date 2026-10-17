# 篮球剪辑大师

固定摄像头篮球视频的本地 Windows 剪辑工具，使用 Python、PyQt5、OpenCV 和 FFmpeg 开发，结合 YOLO / ByteTrack 辅助识别球员。

## 主要功能

- 全部进球集锦与指定球员进球集锦。
- 可移动、缩放的篮筐或篮板监测区域，支持多个区域。
- 宽松区域触发，以及标准、严格的穿越轨迹检测。
- 候选片段回放、补记、删除，直接修改进球状态和球员归属。
- 按状态筛选导出、合并重叠片段，保留原视频声音。
- 中文 / English 界面，可设置播放跳转时长和导出参数。

检测结果是待复核候选，不等同于裁判确认的有效得分。反光、遮挡、相同球衣等情况可能造成误检或漏检，需要人工复核。

## 安装与启动

1. 安装 Python 3.10 或更高版本，并将 Python 加入 PATH。
2. 安装 FFmpeg，确保 `ffmpeg` 和 `ffprobe` 命令可用。
3. 下载或克隆本仓库，在项目根目录运行 `setup.bat`，安装依赖并下载模型。
4. 双击 `启动篮球剪辑大师.bat`，或在项目根目录运行：

```powershell
python -m basketball_master
```

GPU 非必需；CPU 也可运行，但处理速度可能较慢。首次安装依赖和下载模型需要网络。

本仓库提供源码，不包含独立安装包。`basketball_master/launcher.cs` 是可选 EXE 启动器的源码；使用上面的 BAT 或 Python 命令无需编译它。

## 使用

导入视频，框选监测区域，设置分析范围，开始分析；复核候选并选择要导出的片段。指定球员模式可从照片或视频任意时间的画面添加球员样本，不要求球员出现在第一帧。

完整操作说明见 [使用文档](basketball_master/README.md)。

## 测试

在项目根目录运行：

```powershell
python -m pip install pytest
python -m pytest basketball_master/tests -q
```

部分测试使用本地真实视频，没有对应素材时会跳过；仓库不提供原视频。

## 本地数据与依赖

视频、球员照片、项目记录和导出结果在本机处理。个人项目、设置、照片、模型权重、测试输出和原视频已通过 `.gitignore` 排除，不随源码上传。

项目记录位于 `basketball_master/data/`，模型位于 `basketball_master/models/`。安装脚本会下载模型，无需将模型文件提交到 Git。

PyQt5、Ultralytics / YOLO、FFmpeg 等依赖分别遵循其上游许可；分发或商用前请核对相关许可要求。
