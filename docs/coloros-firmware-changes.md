# ColorOS 官方固件到 AVD 的修改清单

核对日期：2026-10-10。范围为当前工作区的 ColorOS 构建与启动代码。

项目使用 OPPO Find X10 Pro Max / PMX110 的 ColorOS 17.0.0.114（Android 17 / API 37）官方 OTA 提供系统内容，使用 Android Studio API 36 Google Play ARM64 revision 7 镜像提供 Ranchu 虚拟硬件环境。官方系统分区经过合并、修改和应用裁剪，再与 AVD 内核及 Vendor 一起打包。

本清单说明当前代码会做什么。已有镜像与 userdata 可能来自较早构建或包含测试时的覆盖文件，不能仅凭源码认定所有修改都已经在运行实例中生效。本文整理期间没有重新构建固件。

## 1. 分区、内核与验证链

| 项目         | 修改内容                                                                                                                                       | 目的及实现                                                                                                                                                  |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 官方系统分区 | 将 `system`、`system_ext`、`product` 和八个 Euclid `my_*` 分区合并进一个 EROFS 系统文件系统；`my_product/product_overlay` 另外覆盖到 `product` | 适配 AVD 的动态分区布局，同时让官方组件继续从原有目录访问文件；[build_coloros.py](../scripts/build_coloros.py)、[erofs_image.py](../scripts/erofs_image.py) |
| ODM          | 选择性提取相机配置和 `libOplusSecurity.so`，写入 Vendor 中的 ODM 路径及所需库目录                                                              | 不将手机的整个 ODM 分区作为 AVD 硬件层使用                                                                                                                  |
| 硬件基底     | 使用 AVD 的 Ranchu Vendor、`system_dlkm`、4 KiB 页 GKI 内核及 ramdisk                                                                          | 替代依赖真实手机硬件的启动及驱动环境                                                                                                                        |
| 挂载表       | 修改 Vendor 和 ramdisk 中的 `fstab.ranchu`，注释独立 `product`、`system_ext` 的四条挂载记录                                                    | 这些内容已合并到系统文件系统，避免再挂载缺失的独立分区                                                                                                      |
| 镜像打包     | 重新生成 GPT / super，包含合并后的 `system`、适配后的 `vendor` 与 AVD `system_dlkm`                                                            | [lp_image.py](../scripts/lp_image.py)                                                                                                                       |
| AVB          | 在 AVD 模板的 `vbmeta` 中将 flags 写为 `3`，关闭 hashtree 与 verification 校验                                                                 | 使重新打包后的镜像能够启动；这与 SELinux 是否 Enforcing 是两项不同设置                                                                                      |

EROFS 合并器保留来源文件的 UID/GID、权限、扩展属性及 SELinux 标签，并为新增或替换文件指定元数据。

## 2. 身份属性、ADB、Root 与服务

| 项目           | 写入镜像的修改                                                                                                                                            | 原因                                                                                                   |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Euclid 属性    | 从 `my_manifest/build.prop` 和 `my_product/build.prop` 收集 OPPO/ColorOS 身份与软件属性，追加到 `product/etc/build.prop`，新增 `system/euclid_build.prop` | 合并后仍能读取官方机型与 Euclid 软件配置                                                               |
| 显示与媒体属性 | 将 `system`、`product` 和 `my_product` 的逻辑密度统一为 560 dpi；媒体配置路径改为 `/vendor/etc/media_profiles_V1_0.xml`；启用 64 位 mediaserver           | 与 1272×2772 的 ColorOS AVD 显示配置、虚拟媒体配置一致                                                 |
| 相机属性       | 指定 `com.oplus.camera`、相机尺寸和 ODM 身份；禁用 `oplus.software.camera.10bit`，设置非哈苏标志                                                          | 避免虚拟相机请求不支持的 JPEG_R/10-bit 等硬件路径；这些身份参数不代表 AVD 具有真实手机的像素或镜头能力 |
| ADB            | 从 AVD 基底复制 `init.ranchu.adb.setup.sh`，合入 Ranchu system_ext 与 radio 初始化内容；在 post-fs-data 设置 USB/ADB 属性                                 | 提供模拟器调试和虚拟无线电初始化                                                                       |
| ADB 认证       | 默认保留认证；仅显式传入 `--diagnostic-adb` 时将 `ro.adb.secure=1` 改为 `0`                                                                               | 诊断开关不是默认固件行为                                                                               |
| KernelSU       | 使用 v3.3.0 的 android15-6.6 LKM 修补 ramdisk，传入 `--allow-shell`，预装管理器 APK                                                                       | 提供项目启动初始化和调试所需 Root                                                                      |
| URCC 服务      | 新增 `vendor.oplus.hardware.urcc-service`，注册 `IUrcc/default`；init 中以 `su` 域启动                                                                    | Binder stub 返回成功响应，补齐原厂客户端依赖，不实现手机的真实资源调度功能                             |
| 相机扩展服务   | 新增 `vendor.oplus.hardware.sendextcamcmd-service`，注册 `ISendExtCamCmdService/default`；从 ODM 提取其 VINTF 声明并改为 framework 类型                   | Binder stub 补齐设备专属相机扩展命令接口，不实现实体 ISP 命令                                          |
| SELinux 上下文 | 扩充 system_ext 的 file/property/service contexts，为 ADB 脚本、模拟器启动属性及新增服务指定标签                                                          | 配合虚拟硬件和服务运行；项目默认要求全局 SELinux Enforcing                                             |

入口：[build_coloros.py](../scripts/build_coloros.py)、[urcc_service.cpp](../native/urcc_service.cpp)、[sendextcamcmd_service.cpp](../native/sendextcamcmd_service.cpp)。构建器通过 Android NDK 从源码编译两个 stub，产物写入工作区的 `work/native-services/`，然后写入镜像。

## 3. 图形与音频兼容

| 文件或设置                                 | 修改                                                                                                           | 解决的问题                                         |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Ranchu composer3 service                   | 修补一条 ARM64 浮点加法指令，使合成器传递原始 plane alpha，避免将其与 brightness 求平均                        | 黑色遮罩淡出后仍半透明、返回动画发暗；保留硬件合成 |
| `system/lib64/libhwui.so`                  | 找到指定 shader 字符串时，将 `uint outlineType = floatBitsToUint(...)` 替换为整数转换                          | OplusCausticShadowEffect 的 GLSL ES 1.00 语法兼容  |
| `system_ext/lib64/libgralloc_extra_sys.so` | 将五个固定偏移的函数入口改为返回 `0`                                                                           | 绕过不适用于 AVD buffer 的 MTK 私有检查或操作      |
| `system_ext/lib64/libged_sys.so`           | 将七个固定偏移的函数入口改为返回 `0`                                                                           | 避免执行真实设备 GPU/GED 私有操作                  |
| 图形属性                                   | 设置 `debug.hwui.renderer=skiagl`、`debug.renderengine.backend=skiavkthreaded`；构建属性和 init 中启用背景模糊 | 配置 UI 与合成渲染路径                             |
| Vendor Zygote 属性                         | 将 `ro.zygote.disable_gl_preload=1` 改为 `0`                                                                   | 调整模拟器 GL 初始化路径                           |
| `vendor/lib64/libtinyalsav2.so`            | 对播放 `pcm_writei` 的 EIO 错误增加一次 stop/prepare 和一次重试                                                | 修复持续丢失播放样本；此补丁不改录音路径           |

入口：[patch_composer.py](../scripts/patch_composer.py)、[patch_audio.py](../scripts/patch_audio.py) 和 [native_patches.py](../scripts/native_patches.py)。composer、tinyalsa、HWUI、gralloc/GED 补丁均绑定已知输入与输出 SHA-256，并核对修改位置的原字节；gralloc/GED/HWUI 匹配规则同时记录在构建元数据中。

## 4. 相机 HAL、CameraUnit SDK 与相机 APK

相机是当前修改最集中的功能，涵盖 AVD Vendor、官方配置、SDK JAR 和相机 APK。

### HAL 与配置

- 修补 Ranchu camera provider，将后摄 ID 基数从 `10` 改为 `0`，加载项目的 `libhyperos_avd_scene.so`。
- 桥接库补充相机角色、Oplus camera type、YUV 格式及普通流尺寸 metadata；为虚拟场景后摄实现 1×–4×数码裁剪，并处理对应图像 buffer。后摄来源为 `virtualscene`，前摄为 `emulated`。
- 从官方 ODM 提取相机 JSON/protobuf；公开相机 ID 限定为 `0`、`1`，过滤 RAW、tuning、DOL 等流和私有 operation mode，清空多摄关联，关闭 MTK insensor zoom、tuning buffer 支持。
- 将照片、专业、夜景等 use case 的流组合改为普通 preview/capture；保留入口不等于已实现原厂算法。
- 删除配置与 feature protobuf 中的人像模式记录，并重新生成符合 OEM 大端读取格式的 `oplus_camera_feature_config`。
- 扩充两颗虚拟相机的 720p/1080p30 录像 profile，使用 MP4、H.264 和 AAC（48 kHz、单声道、96 kbps），扩充 H.264 尺寸上限。
- 将 ODM 的 `libOplusSecurity.so` 放入所需 Vendor/ODM/product 库目录，并将 `my_product/lib64` 的 `.so` 复制到 `product/lib64`，补齐官方相机 JNI/渲染库加载路径。

入口：[patch_camera_scene.py](../scripts/patch_camera_scene.py)、[camera_scene_roles.cpp](../native/camera_scene_roles.cpp)、[coloros_camera_profiles.py](../scripts/coloros_camera_profiles.py) 和构建器的 `virtual_camera_config`。

### CameraUnit SDK JAR

修改 `product/framework/com.oplus.camera.unit.sdk.jar` 中的 DEX：

- 绕过阻塞初始化的特定调用，强制执行完整配置初始化，保留 vendor-tag readiness 回调。
- 将自定义相机类型回退到公开 Camera ID；软件 APS 的拍照 tag 使用逻辑相机 ID，避免引用前摄的内部 physical ID。
- 选择 `NoneApsImpl` 软件 APS，关闭对实体 ISP capture 的声明，跳过缺失的可选 MTK/Oplus capture metadata。
- 按 YUV 每个平面的 row stride / pixel stride 转换 NV21，替代直接复制 VU 平面的假设。
- 将请求中的拍照方向写入 JPEG EXIF。
- 启用相机 SDK 现有的 logcat 日志回退。
- 删除 product 中对应的旧 `.odex`、`.vdex`，使修改后的 JAR 生效。

入口：构建器的 `patch_camera_sdk_jar`、[coloros_camera_yuv.py](../scripts/coloros_camera_yuv.py)、[coloros_camera_capture.py](../scripts/coloros_camera_capture.py)。

### 官方相机 APK

修改 `my_product/app/OplusCamera/OplusCamera.apk` 中的多个 DEX，加入项目 Java 适配类：

- 禁用 BaseMode 的私有 ISP quick-JPEG 请求，并调整仍然依赖 tuning/副摄的 capture stream 查询。
- 对美颜、妆容、人像、景深、face blur、双摄与 RAW 相关能力返回不支持，绕过在 Ranchu 上可能生成空纹理的美颜处理器。
- 在模式数据库查询、动态快捷方式发布中过滤人像；禁用已有的固定人像快捷方式，处理旧 userdata 缓存入口。
- 将后摄离散倍率映射到 1×–4×数码变焦，结合 HAL 的最大倍率调整查询；关闭不适合后摄的 front-wide zoom 路径。
- 对曝光调节步进设置最小值 `1`，避免虚拟 metadata 的小数步进转换为整数后成为 `0`。
- 按录像 profile 预初始化 persistent input surface，避免 Camera2 拿到默认 1×1 的录制 surface。
- 在缺少 `MicrophoneInfo` 描述、但确实存在 built-in mic 输入路由时，补齐官方相机的麦克风可用判断。
- 为预览/全景提供独立 NV21 平面副本，避免异步处理复用 buffer；缺失的全景可选 vendor tag 返回 `null`。
- 重写 DEX 后检查其格式，并重新执行 APK ZIP 对齐，包含 16 KiB 原生库页对齐。

入口：[coloros_camera_buffers.py](../scripts/coloros_camera_buffers.py)、[PatchCameraDex.java](../native/coloros_camera/PatchCameraDex.java)、[VirtualCameraBuffers.java](../native/coloros_camera/VirtualCameraBuffers.java)。这属于修改官方 APK 内容，不能将产物描述为字节不变的原厂 APK。重建 ZIP 后通过 [apk_system_signing.py](../scripts/apk_system_signing.py) 保留原厂 APK Signing Block，供可信系统分区扫描读取证书身份；这不等于对修改后的内容重新签名，修改后的 APK 不可作为普通用户 APK 通过完整签名验证安装。项目没有因此全局关闭 Android 应用签名检查。

现有验证记录支持前后摄拍照、部分 720p/1080p 录像及 AAC 音轨、后摄 2×裁剪和专业模式拍照。前摄缩放未通过；实体多摄没有提供；4K/60fps、HDR、夜景算法等没有完整验收。详见 [相机验证记录](coloros-camera-validation.md)，其中不同测试覆盖组合的历史结果需要分别理解。

## 5. 壁纸和应用裁剪

构建器保留默认主题映射中的三个 OEM Mars 视频壁纸服务，并将其 BT.709 SDR / HEVC Main 10 视频转成 8-bit AVC，使 Ranchu 解码器可以播放；保留 1272×2772、60 fps、1.7 秒及有限范围 BT.709 标记。默认组件仍为 `Mars1VideoWallpaper`、`Mars2VideoWallpaper` 和 `Mars3VideoWallpaper`。启动器不设置壁纸；原厂静态资源保留在 OTA 的原有路径，自定义静态壁纸辅助程序及 `system/etc` 副本已移除。

该转码是有损的 10-bit 到 8-bit 兼容处理，不是系统全局色域补丁。设备解码错误、三种壁纸播放和颜色抽样记录见 [动态壁纸验证](coloros-wallpaper-validation.md)。

当前构建移除用户指定的应用壳，未列入名单的系统组件保留。删除的应用目录包括 APK、oat 和相关 sidecar 文件：

| 应用             | 镜像中的删除目录                              |
| ---------------- | --------------------------------------------- |
| 我的 OPPO        | `my_stock/del-app/KeKeUserCenterMember`       |
| OPPO 商城        | `my_stock/del-app/OPPOStore`                  |
| 小游戏           | `my_stock/del-app/OplusQuickGame`             |
| 游戏中心         | `my_stock/del-app/Gamecenter`                 |
| 指南针           | `my_stock/del-app/OppoCompass2`               |
| 笔记             | `my_stock/del-app/OppoNote2`                  |
| 笔记本           | `my_stock/del-app/AIPaper`                    |
| AI 拍一拍        | `my_stock/del-app/OcrScanner`                 |
| 录音             | `my_stock/del-app/NewSoundRecorder`           |
| 邮件             | `my_stock/del-app/OplusEmail`                 |
| 文档阅读器       | `my_stock/del-app/OplusDocumentsReader`       |
| 翻译             | `my_stock/del-app/OppoTranslation`            |
| 家人守护         | `my_stock/del-app/FamilyGuard`                |
| 使用技巧         | `my_stock/del-app/Tips`                       |
| 禅定空间         | `my_stock/del-app/OPBreathMode`               |
| 逍遥游           | `my_stock/priv-app/TravelEngine`              |
| 手机搬家         | `my_stock/del-app/BackupAndRestore`           |
| OPPO 视频        | `my_stock/del-app/BrowserVideo`               |
| 音乐             | `my_stock/del-app/Music`                      |
| 钱包             | `my_stock/del-app/FinShellWallet`             |
| 搜狗输入法定制版 | `my_product/del-app/SogouInput_U_Product_Del` |
| 书城             | `my_product/del-app/heytapbook`               |
| 红外遥控         | `my_product/priv-app/RemoteControl`           |

这些删除在重新构建时应用。`MyDevices`、媒体播放器 `VideoGallery`、Android `DocumentsUI` 以及其他未列入名单的系统组件会保留。

## 6. AVD 默认值与启动后的操作

这些属于模拟器配置或 userdata 初始化，不是对官方只读系统文件的直接修改。

| 时机           | 行为                                                                                                 | 实现                                                                             |
| -------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 创建实例       | 4 核、6 GiB RAM、16 GiB data、1272×2772 / 560 dpi、60 Hz、host GPU、音频输入输出、虚拟前后摄、冷启动 | 构建器生成 ColorOS 专用 `avd.ini`                                                |
| 创建 data 模板 | 创建空白 16 GiB ext4，启用 encrypt/quota/project/casefold；已有模板存在时直接复用                    | [init_userdata.py](../scripts/init_userdata.py)                                  |
| 启动前         | 保留已有 userdata；按照实例配置核验实际 ext4 容量，暂存并验证 raw/QCOW2 修改，拒绝缩小                                | [launch.py](../scripts/launch.py)、[avd_userdata.py](../scripts/avd_userdata.py) |
| 启动后扩容     | 读取解密设备的 ext4 超级块，核验容量、UUID 和挂载身份；必要的加密扩容通过有离线备份的受控来宾执行                             | ColorOS fstab 没有自动 resize 标志，仅扩大镜像不足以扩大 ext4                    |
| 传感器与显示   | 设置 proximity=5、light=200；设置很长的熄屏时间；唤醒屏幕并尝试解除锁屏                              | ColorOS 启动初始化                                                               |
| Root 初始化    | 必要时安装设备端 ksud；关闭 KernelSU 的 `selinux_hide`，检查 Root 与 Enforcing；管理器缺失或仅为系统预装时安装到 `/data/app`，提取所需原生库 | ColorOS 启动初始化 |
| 服务恢复       | 如果 URCC stub 未运行，尝试从 Root shell 补启动                                                      | ColorOS 启动初始化                                                               |
| 可选跳过引导   | 仅 `--skip-oobe` 时设置 provisioned/setup complete，禁用当前用户的 bootreg/provision，进入原生桌面   | 不默认删除首次开机引导 APK                                                       |

此前当前实例的 data 已由 6 GiB 扩到 16 GiB，备份了用户数据与加密密钥，冷启动后 `/data` 显示约 10 GiB 可用。已有模板不会因默认值改动被自动重建；当前空白模板为 16 GiB。启动流程负责核验容量，并在扩容前检查镜像占用、保存备份和恢复中断的离线事务。

## 7. 构建产物与运行时覆盖的区别

相机验证中曾通过 userdata 中的文件和 bind mount 临时覆盖 APK、SDK、相机 JSON/protobuf、录像 profile 和桥接库。它们可能在保留 userdata 的情况下继续存在，并影响实际加载内容；相机报告已经记录部分运行文件与镜像哈希不同。

这些测试覆盖不是 `launch.py` 的常规 ColorOS 初始化步骤。判断当前实例实际使用哪个版本，需要结合镜像与运行文件 SHA-256、挂载信息和测试记录。最新的应用删除、默认 data 大小等源码修改，也需要分别确认其构建或启动生效条件。

项目已清理其他系统的构建、安装器与专用补丁。`libhyperos_avd_scene.so` 是沿用的内部二进制依赖名称，目前由 ColorOS 相机 provider 实际使用；清理保留该名称及兼容 metadata，避免改变已验证 provider 的哈希和加载接口。
