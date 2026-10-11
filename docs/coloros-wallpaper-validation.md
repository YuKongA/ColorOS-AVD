# ColorOS 默认动态壁纸验证

2026-10-11，Apple Silicon / Ranchu API 36 ARM64 基底，ColorOS 17.0.0.114。

原始 `WallpaperChooser.apk` 包含 `Mars1VideoWallpaper`、`Mars2VideoWallpaper`、`Mars3VideoWallpaper` 服务，默认配置所指向的组件确实存在。Mars 视频为 1272×2772、60 fps、102 帧、1.7 秒，编码为 HEVC Main 10 / `yuv420p10le`，色彩标记为有限范围 BT.709 SDR。10-bit 本身不表示 HDR。

在当前 AVD 上直接选择原始 Mars1 服务时，桌面背景黑屏。设备日志显示 `c2.goldfish.hevc.decoder` 的 `GoldfishHevcHelper` 报 `error in decodeHeader: 0x43dd`，随后 `MediaPlayer` 报 `Error (1,-2147483648)`。这证实该默认播放路径存在解码兼容问题；此前“手动设置一定走 ColorfulEngine”以及“色域转换导致发白”的说法没有足够证据。

构建器现在保留原厂默认主题 XML 和 WallpaperChooser APK，只将三个 Mars 视频转成 H.264 High / 8-bit `yuv420p`，显式保留有限范围 BT.709，尺寸、帧率、帧数及时间不变。启动器移除了每次启动设置静态壁纸的逻辑。

| 验证项 | 结果 |
| --- | --- |
| 镜像内默认配置 | 包含原始 Mars1/2/3 服务，无 ColorfulEngine 替换 |
| 三个转码视频 | ffprobe 元数据正确，FFmpeg 完整解码通过 |
| 三个原厂 Mars 服务 | 新镜像上可显示，无壁纸解码错误 |
| 色彩抽样 | 左侧无图标区域与转码参考帧的 RGB 平均绝对误差为 2.26、3.16、1.75（0–255 标度） |
| 转码损失 | 与原视频最后一帧的 RGB 平均绝对误差为 1.93、2.10、2.06（0–255 标度） |
| 现有实例冷启动 | 保留 Mars1 选择，画面正常，无视频文件 bind mount |
| 独立新 userdata | 首次开机自动选择 Mars1；随后有窗口冷启动画面正常 |
| Root / SELinux | 两个实例均为 uid=0 / Enforcing |

像素比较只覆盖最后一帧及选定的无 UI 遮挡区域，不能证明整条显示链路在所有视频上都不存在色彩问题。转码是有损的 10-bit 到 8-bit 兼容处理，没有修改系统全局色彩参数；实际播放达到 60 fps 未测量。独立实例的无窗口模式截图为全黑，因此画面验收使用有窗口模式。

原始解码日志、三个版本的截图和参考帧、比较结果及冷启动记录保存在本地 `work/coloros/diagnostics/wallpaper-validation/`。临时 QA 实例已注销并删除测试 userdata；主实例保留。
