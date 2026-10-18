# 篮球剪辑大师

固定摄像头篮球视频的本地 Windows 剪辑工具，使用 Python、PyQt5、OpenCV 和 FFmpeg 开发，结合 YOLO / ByteTrack 辅助识别球员。

**[六步截图教程](docs/usage-guide.md)** · **[分析原理与测试说明](docs/how-it-works.md)** · [完整功能说明](basketball_master/README.md)

![篮球剪辑大师：视频预览、篮板区域标定和候选进球复核界面](docs/images/overview.png)

截图中的记录是待复核入框候选，不代表已经确认的有效进球。

## 主要功能

- 全部进球集锦与指定球员进球集锦。
- 可移动、缩放的篮筐或篮板监测区域，支持多个区域。
- 篮板区域进入与篮圈穿越独立标定；区域模式结合连续轨迹与球体模型复核，强轨迹但模型不确定时保留待复核。
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

BAT 启动器会优先读取安装时保存的 `basketball_master/python-path.txt`，自动将 `pythonw.exe` 切换为同目录的 `python.exe`，以便显示报错；路径失效时再查找本地虚拟环境、Python Launcher、PATH 和常见 Python / Anaconda 安装目录。它会验证 Python 3.10+ 并跳过 Windows 商店快捷入口，不必为此修改系统的应用执行别名。找不到真实 Python 时会保留窗口并提示处理方法；新安装环境请从 Python / Anaconda 终端运行 `setup.bat` 安装依赖。

## 使用

导入视频，框选监测区域，设置分析范围，开始分析；复核候选并选择要导出的片段。指定球员模式可从照片或视频任意时间的画面添加球员样本，不要求球员出现在第一帧。

初次使用可按 [六步截图教程](docs/usage-guide.md) 操作，每一步都有真实界面和箭头提示。软件右上角“帮助 → 图形引导”也能逐步定位按钮。

检测方法、树叶与反光过滤、球员归属、167.8 秒后片段的验证结果及局限，见 [分析原理与测试说明](docs/how-it-works.md)。更多操作细节见 [完整功能说明](basketball_master/README.md)。

## 测试

在项目根目录运行：

```powershell
python -m pip install pytest
python -m pytest basketball_master/tests -q
```

部分测试使用本地真实视频，没有对应素材时会跳过；仓库不提供原视频。

## 本地数据与依赖

视频、球员照片、项目记录和导出结果在本机处理。个人项目、设置、球员样本、模型权重、运行输出和原始 MP4 等视频素材不随源码上传；文档仅附必要的界面截图和诊断示意图。不要提交其他未被忽略规则覆盖的个人素材或相机附属文件。

项目记录位于 `basketball_master/data/`，模型位于 `basketball_master/models/`。安装脚本会下载模型，无需将模型文件提交到 Git。

PyQt5、Ultralytics / YOLO、FFmpeg 等依赖分别遵循其上游许可；分发或商用前请核对相关许可要求。
