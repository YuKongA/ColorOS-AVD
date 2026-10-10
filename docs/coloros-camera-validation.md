# ColorOS 相机验证：2026-10-10

## 当前运行实例复测（15:17–15:22，Asia/Shanghai）

这次复测针对当时正在运行的 `emulator-5574`，其 userdata 已被多轮运行时覆盖使用；结果不能替代重新构建镜像后的冷启动验收。证据目录为 `work/coloros/diagnostics/camera-audit-20261010/`。

| 能力          | 当前结果       | 证据                                                                                                                                                |
| ------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 后摄拍照      | 通过           | `rear-photo-1x.jpg`、`rear-photo-2x.jpg`，均为 1920×1440 JPEG                                                                                       |
| 前摄拍照      | 通过           | `front-photo.jpg`、`front-photo-zoom.jpg`，模拟器测试图案正常                                                                                       |
| 前后摄切换    | 通过           | 当前实例可从后摄切到前摄并返回，两个 Camera2 设备均有持续预览                                                                                       |
| 后摄录像      | 通过           | `rear-video-current.mp4`：H.264 1280×720，170 帧，AAC 音轨 264 包，5.68 s                                                                           |
| 前摄录像      | 通过           | `front-video-current.mp4`：H.264 1920×1080，144 帧，AAC 音轨 224 包，4.88 s                                                                         |
| 后摄倍率      | 通过           | 候选补丁和冷启动实例中，点击 `2×` 后预览明显裁剪，Camera2 请求/结果为 `zoomRatio=2.0`；点击 `1×` 恢复 `zoomRatio=1.0`。连续 3 轮 1×→2×→1×→2× 均通过 |
| 前摄倍率      | 未通过         | 双指注入成功但请求仍约 `1.17`、cropRegion 仍为完整 `1920×1440`，没有可见倍率变化                                                                    |
| 人像模式      | 已彻底移除入口 | 配置、feature protobuf、模式数据库查询和桌面动态快捷方式均过滤 `portrait_mode`；最终镜像的 `dumpsys shortcut` 已无 `shortcut_portrait_static`       |
| 美颜/妆容     | 已关闭         | Camera APK 的能力查询统一对 beauty/makeup/bokeh/face-blur 返回不支持，避免前摄美颜黑屏                                                              |
| 专业模式      | 当前复测通过   | 专业模式预览正常；清理 AVD 测试媒体后成功生成 `IMG20261010153855.jpg`（1920×1440）。此前失败是 `/data` 仅剩约 199 MB 触发“手机空间不足”             |
| 多摄/焦段切换 | 不适用/未提供  | AVD 只有后摄 Camera ID 0（单焦距 1.0）和前摄 Camera ID 1（焦距 4.38）；没有超广角、长焦实体设备                                                     |

本轮视频已出现 AAC 轨道，因此旧记录中“录像无音轨”只适用于先前的运行时覆盖组合。当前前摄画面也能正常显示；美颜和人像入口已关闭。4K/60fps、HDR、夜景、RAW 和慢动作仍未覆盖。

最终冷启动镜像中的相机 APK SHA-256 为 `69bd8d3e01147c8eb294286da2d6467db2f61a94a8a60217acd97443a2a93732`。候选实例生成的 1× 和 2× JPEG 均保存成功；专业模式仍能生成 1920×1440 JPEG。

当前运行文件 SHA-256 与镜像构建值不同，说明 userdata 上确实存在运行时替换：`OplusCamera.apk=3725965b…`、`camera_unit_config=a33020a2…`、`libhyperos_avd_scene.so=9e64da71…`；基础 provider 仍为构建时的 `4f43f58f…`。完整哈希见 `runtime-hashes.txt`，覆盖顺序见 `init-mountinfo.txt`。

## 原版 ColorOS 到 AVD 的修改清单

这些是构建器和启动器对 OPPO OTA 原版所做的适配，按“写入镜像”和“启动时注入”区分。完整清单及当前应用裁剪、16 GiB data 配置见 [ColorOS 固件修改说明](coloros-firmware-changes.md)：

- **分区与身份**：将 `system`、`system_ext`、`product` 及 `my_*` Euclid 分区以 EROFS 合并为单一系统镜像；从 `odm` 选择性提取相机配置和库。保留 ColorOS/OPPO 身份属性，补充 `euclid_build.prop`，统一为 560 dpi，并调整相机能力属性。
- **启动与安全**：把 KernelSU v3.3.0 LKM 打入 API 36 ARM64 4KB ramdisk，合并 Ranchu fstab，保持 SELinux Enforcing；预装 KernelSU 管理器，启用 ADB 启动脚本。
- **图形与音频**：修补 Ranchu HWC 的 alpha 指令和 `libged/libgralloc_extra_sys` 的 AVD buffer 检查；设置 `skiagl`/`skiavkthreaded`；对 `libtinyalsav2.so` 增加一次 EIO 播放恢复，录音路由本身保持 AVD 音频输入。
- **相机 HAL**：将 Ranchu 后摄绑定 `virtualscene`、前摄绑定 `emulated`；修改 provider 的后摄 ID/metadata，注入角色、普通流尺寸、YUV/JPEG/RGBA/RAW16 声明和后摄 1×–4×裁剪桥；增设 `sendextcamcmd` 与 `urcc` Binder stub 服务及 VINTF/SELinux 规则。
- **ColorOS CameraUnit/应用**：过滤 MTK RAW、tuning、DOL 和多摄 use case，强制走普通 Camera2/软件 APS；移除不存在的实体镜头和 ISP 依赖；修正 CameraUnit 初始化、Camera ID、APS capture、YUV 行跨度/像素跨度、EXIF 方向、视频 persistent surface、CamcorderProfile 720p/1080p30 和麦克风检查；禁用依赖实体 ISP 的美颜、景深、RAW 等路径。
- **运行时覆盖**：本次 userdata 还被多轮 APK、SDK、JSON、feature protobuf、媒体 profile 和 scene bridge 临时替换；这些覆盖会随着当前 userdata 保留，不能当作干净冷启动镜像的固定内容。

对应实现入口是 `scripts/build_coloros.py`、`scripts/patch_camera_scene.py`、`scripts/coloros_camera_buffers.py`、`native/camera_scene_roles.cpp` 和 `native/coloros_camera/VirtualCameraBuffers.java`。

镜像清理还会移除用户指定的非必要应用：我的 OPPO、OPPO 商城、小游戏、游戏中心、指南针、笔记、录音、邮件、文档阅读器、翻译、家人守护、使用技巧、禅定空间、逍遥游、手机搬家、OPPO 视频、音乐、钱包、搜狗输入法定制版、书城和红外遥控。新增删除项在重新构建后生效。Android 核心 `DocumentsUI` 保留，用于系统文件选择器；本次 OTA 中未发现独立的“股市”APK 或“拍一拍”应用包。

以下是同日较早覆盖组合的历史结果；它保留用于解释此前的问题来源，当前运行实例结果以“当前运行实例复测”一节为准。普通前后摄 JPEG 拍照可用，前摄预览和录像需要关闭美颜。前后摄 720p/1080p 视频均能保存和解码，但测试成片没有音轨。多焦段、缩放、人像拍摄及部分模式切换未通过。

## 环境与范围

- Apple Silicon Mac，运行中的 `ColorOS17_API37`，ADB `emulator-5574`。
- ColorOS 17.0.0.114 / Android API 37，1272×2772 竖屏、560 dpi，全局 SELinux Enforcing。
- 后摄 ID `0`：Ranchu `virtualscene` 房间；前摄 ID `1`：Google emulated 测试画面。
- 原生相机 `com.oplus.camera`；先测试 CameraImageActivity / CaptureVideoActivity 路径，再通过桌面入口 `.Camera` 复核普通拍照、前后摄录像及缺少音轨的问题。
- 验证使用已有 userdata 和运行时绑定的相机 APK / 配置。结果对应当前运行状态，尚未验收重新构建镜像后的冷启动、全新 userdata 或长期稳定性。

本轮未修改相机 SDK、APK 或 HAL，新增验证记录、截图和双指输入工具。临时关闭前摄美颜属于应用设置，不能视为兼容性补丁。

## 功能结果

| 功能                        | 结果             | 验证依据                                                                                                                                                       |
| --------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 后摄普通拍照                | 通过             | 连续两张 1920×1440 JPEG，房间、棋盘及颜色正常；桌面入口再次生成照片                                                                                            |
| 前摄普通拍照                | 通过             | 美颜开启、关闭均生成 1920×1440 JPEG，内容为模拟器测试图案；桌面入口复核                                                                                        |
| 后摄预览                    | 通过             | 拍照、视频均有持续更新的虚拟房间画面                                                                                                                           |
| 前摄预览                    | 有条件通过       | 默认美颜路径黑屏；照片选择“无美颜”，视频美颜强度调到 `0` 后恢复                                                                                                |
| 前后摄切换                  | 有条件通过       | 关闭前摄美颜后连续 5 轮前→后切换，均恢复对应画面；切换不能消除美颜黑屏                                                                                         |
| 后摄 1080p/30、720p/30 录像 | 视频画面通过     | H.264 MP4 可完整解码，平均帧率约 29.9；720p 视频验证了暂停、继续、停止                                                                                         |
| 前摄 1080p/30、720p/30 录像 | 有条件通过       | 美颜 `0` 时 H.264 视频有测试图案，平均帧率约 29；美颜 `30` 时视频全黑                                                                                          |
| 录像声音                    | 未通过           | 所检查 MP4 仅一个 H.264 视频轨，没有 AAC 或其他音轨；桌面入口也复现                                                                                            |
| 相册视频回看                | 通过基础画面检查 | 点击后摄录像缩略图可在原生相册显示、播放对应房间画面                                                                                                           |
| 录像中拍照                  | 未通过本次尝试   | 后摄录像过程中点击独立拍照按钮，MediaStore 与 DCIM 未新增 JPEG                                                                                                 |
| 后摄镜头焦段切换            | 当前未提供       | 只有一个公开后摄，UI 只有 `1×`，没有超广角、3×、6× 后摄设备                                                                                                    |
| 后摄缩放                    | 已修复           | 旧覆盖中点击 `2×` 只切换了实体镜头状态，Ranchu 单后摄请求仍为 1.0；最终适配将离散倍率直接映射为 1×–4× 数码裁剪，点击 2× 和双指缩放均提交真实 Camera2 zoom 请求 |
| 前摄缩放                    | 未通过           | 双指放大后请求仍为 `1.0`，裁剪区域仍为完整 1920×1440；没有倍率入口                                                                                             |
| 人像拍照                    | 未通过           | 模式可预览，点击快门未新增照片；虚化算法未验收                                                                                                                 |
| 人像→照片→专业模式切换      | 未通过           | 触发输入超时 ANR，相机被系统结束，重新启动后恢复                                                                                                               |
| 后摄全景                    | 通过基础流程     | 开始后停止，生成 1440×1920 JPEG；仅验证静态场景，未验证移动扫拍拼接                                                                                            |

4K、60fps、夜景、HDR、RAW、慢动作、延时摄影、萌拍、文档、美颜效果和实际光学变焦未完成成片验收。录像菜单本轮只提供 720p/1080p 与 30fps。

## 问题复现与定位

### 前摄美颜使预览、录像全黑

1. 照片模式切换前摄，打开美颜并选择“默认”。
2. 预览全黑，但 Camera2 仍输出帧；按快门可保存有内容的 JPEG。
3. 美颜选择“无美颜”，预览立即恢复。
4. 视频模式的美颜强度 `30` 同样使预览和成片全黑；把美颜滑尺向右拖到 `0` 后，预览和成片恢复。

黑色视频 `VID20261010121009.mp4` 共 331 帧，FFmpeg `signalstats` 检查所有帧的平均亮度均为 `16`，证实成片全黑。日志出现 `OCAM_GLES20Canvas: GL error: 1282` 和 gfxstream `glTexSubImage2D` 空像素错误；现有证据指向美颜渲染路径，尚未定位具体原厂算法调用。

| 照片默认美颜                                                                         | 照片关闭美颜                                                                         | 视频美颜 30                                                                                 | 视频美颜 0                                                                                 |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| ![默认美颜黑屏](../screenshots/coloros/camera-validation-20261010/front-preview.png) | ![关闭后恢复](../screenshots/coloros/camera-validation-20261010/front-no-beauty.png) | ![视频黑屏](../screenshots/coloros/camera-validation-20261010/front-video-beauty-retry.png) | ![视频恢复](../screenshots/coloros/camera-validation-20261010/front-video-beauty-zero.png) |

### 录像缺少音轨

从桌面启动相机，选择视频，录制并停止，然后拉取 MP4：

```sh
adb -s emulator-5574 shell am start -n com.oplus.camera/.Camera
adb -s emulator-5574 pull /sdcard/DCIM/Camera/VID20261010122713.mp4 /tmp/coloros-video.mp4
ffprobe -v error -show_streams -show_format -of json /tmp/coloros-video.mp4
```

桌面入口的后摄样本也只有 `codec_type=video, codec_name=h264`。`RECORD_AUDIO` 已授予，AVD 的 `hw.audioInput=yes`；不能将此结果解释为麦克风声音小或相册静音，因为文件本身没有音轨。录制日志还报告不支持 `vendor.ozoaudio.*` 参数，但尚未证明它们是缺少音轨的直接原因。

### 焦段与缩放

HAL 后摄声明 `zoomRatioRange=[1,1]`、`availableMaxDigitalZoom=1`，只有一个焦距值 `1.0 mm`。前摄声明 `zoomRatioRange=[1,12.9319582]`、焦距 `4.38 mm`，但相机 App 的前摄手势未改变倍率。上述 HAL 焦距不等同于手机 UI 的 35mm 等效焦距；Ranchu 未提供 OPPO 的等效焦距 vendor tag，视频日志因此持续报告读取失败。

后摄需要实现实际裁剪/缩放后再扩展能力声明；仅提高 metadata 中的最大倍率不能建立缩放功能。前摄需进一步检查 OEM 配置与缩放请求提交路径。0.6×/3×/6× 的实体镜头不存在于当前 AVD，不能用一个后摄设备证明多镜头切换支持。

双指注入工具及使用方式见 [设备测试说明](../tests/coloros_camera/README.md#缩放手势)。本轮同时检查预览、倍率和 Camera2 请求，避免把输入注入成功视为缩放成功。

### 人像拍摄、专业模式切换卡住

复现路径为视频测试后进入照片，切换人像并拍摄，返回照片后尝试进入专业模式及点击快门。人像未生成照片；后续相机发生 ANR，被系统结束。

12:22:16 与 12:22:21 的 Camera3 日志显示 `Set of requested inputs/outputs not supported by HAL`。12:22:33 系统报告相机输入分发超时。ANR 主线程堆栈停留在 `CopyOnWriteArrayList.add → HSPanelContainer → CaptureParamView → CaptureParamPresenter`。当前证据证明这一切换序列异常，尚未将单独专业模式拍摄和人像算法故障完全隔离。

录像预配置还多次出现 `MediaRecorder.prepare failed: -38` / `Output file descriptor is invalid`，即使最终录像成功也有这些日志，不能仅按错误行判定整个录像失败。

## 成片与证据

以下文件是本轮生成的样本，位于设备 `/sdcard/DCIM/Camera/`：

| 文件                                             | 用途                 | 容器/画面验证                                        |
| ------------------------------------------------ | -------------------- | ---------------------------------------------------- |
| `IMG20261010120808.jpg`、`IMG20261010120814.jpg` | 后摄连续拍照         | 1920×1440，正常房间                                  |
| `IMG20261010120902.jpg`、`IMG20261010121307.jpg` | 前摄拍照             | 1920×1440，模拟器图案                                |
| `VID20261010120945.mp4`                          | 后摄 1080p           | 11.703 s / 350 帧，有画面，无音轨                    |
| `VID20261010121009.mp4`                          | 前摄美颜 30          | 11.226 s / 331 帧，全黑，无音轨                      |
| `VID20261010121603.mp4`                          | 前摄美颜 0，720p     | 7.883 s / 231 帧，有画面，无音轨                     |
| `VID20261010121744.mp4`                          | 前摄美颜 0，1080p    | 7.964 s / 234 帧，有画面，无音轨                     |
| `VID20261010121812.mp4`                          | 后摄 720p，暂停/继续 | 38.135 s / 1142 帧，有画面，无音轨                   |
| `IMG20261010122429.jpg`                          | 后摄全景开始/停止    | 1440×1920，有房间画面                                |
| `VID20261010122713.mp4`                          | 桌面相机入口复核     | 后摄 720p / 7.670 s，无音轨                          |
| `VID20261010122836.mp4`                          | 桌面相机入口复核     | 前摄美颜 0，1080p / 6.953 s / 202 帧，有画面，无音轨 |
| `IMG20261010122852.jpg`、`IMG20261010122859.jpg` | 桌面相机入口复核     | 前、后摄均生成 1920×1440 JPEG                        |

原始截图、照片/视频副本、ffprobe JSON、Camera2 dumps、黑色视频逐帧亮度以及 ANR 保存在本地 `work/coloros/diagnostics/camera-validation/`。完整 ANR 对应设备文件 `/data/anr/anr_3930_2026-10-10-12-22-31-034`。公开截图保存在 `screenshots/coloros/camera-validation-20261010/`。

视频检查使用 `ffprobe` 核对轨道、尺寸、帧数，使用 FFmpeg 完整解码；桌面入口前摄样本另按源时间基解码并检查全部 202 个包的 PTS/DTS 严格递增。照片和视频方向包含 EXIF/容器旋转信息，编码宽高与竖屏显示宽高可能相反。

运行时 APK SHA-256：`be2381cdd193258922bce8689f15673fc2a794ef6f5f577db7fe782e52bde486`；CameraUnit SDK JAR：`88b20bf2124460bdd2242127cfbc90d8e498b4560d7351464773a458aaccbcdf`；feature config：`45afb2fd0955f2dc2ec758aaec25b0138ca82e5c899b933fdeccae2769bebde8`。

已有配置回归测试两项通过；设备 `CameraYuvTest` 的五种平面布局、数组复用、缓冲区位置及 EXIF 0/90/180/270 度测试通过。这些测试证明图像转换与编码，不覆盖美颜、录音、多镜头或完整模式兼容性。
