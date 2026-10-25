# 适配新的固件

构建器只接受已审计的 OTA。每个固件在 [firmware_profile.py](../scripts/firmware_profile.py) 里有一份配置，以 OTA 的 SHA-256 为键，写明这份固件需要哪些移植和修复。`build_coloros.py` 只读配置，不判断机型。

## 配置字段

| 字段 | 含义 |
| --- | --- |
| `native` | 已审计的原生库补丁，见 [native_patches.py](../scripts/native_patches.py)。每个补丁都核对输入哈希、原字节和输出哈希。 |
| `wallpapers` | 需要转成 8-bit AVC 的原厂动态壁纸视频。Ranchu 的解码器解不了 HEVC Main 10。 |
| `ports` | 只存在于部分固件的功能移植：`mtk_graphics`（联发科图形库）、`camera`、`aod`、`double_tap`。 |
| `fixes` | 非联发科固件需要的兼容修复，见下表。 |
| `hwui_renderer` | HWUI 的渲染器，`skiagl` 或 `skiavk`。 |
| `emulator_features` | 启动器给模拟器传的 `-feature` 设置，`-名称` 表示关闭宿主机特性。构建时写进 `local/build.json`，没有就不传。 |
| `removals` | 在共用删除名单之外，这个固件还要从镜像里去掉的文件。 |

`hwui_renderer` 为 `skiavk` 时，Zygote 不能预加载 GPU（`ro.zygote.disable_gl_preload` 保持 1）。Vulkan 预加载会让 Zygote 留下一个打开的 `/dev/goldfish_pipe_dprctd`，fork `system_server` 时 ART 因为它不在白名单里直接 abort，系统开机循环。配置里的 `gl_preload` 属性已经按这条规则推出。

## 修复项

| 修复 | 解决的问题 |
| --- | --- |
| `ethernet_feature` | 固件没有声明 `android.hardware.ethernet`，系统不启动以太网服务，OPlus 的 `OplusJPSbTetherManager` 在开机完成时拿到空的 `EthernetManager`，`system_server` 崩溃循环。 |
| `qti_perf_preload` | 高通性能类 `com.qualcomm.qti.Performance` 的原生方法没绑定。Zygote 只在 `Build.isQcomPlatform()` 为真时加载 `qti_performance`，而它由 `ro.boot.hardware` 以 `qcom` 开头决定，这里必须是 `ranchu`。构建时给 `framework.jar` 打补丁，让它无条件加载。 |
| `flat_display` | AVD 的屏幕是普通矩形。去掉面板的圆角和挖孔：叠加一个 overlay 清零框架里的圆角半径和挖孔，删掉 OPlus 的圆角遮罩 overlay，并在开机时设 `debug.disable_screen_decorations=true`。后者才是关闭窗口里圆角和圆点的开关，因为 OPlus 的 SystemUI 用自带图片画圆角，和框架配置无关。 |
| `launcher_unirender` | 把 `my_product/etc/sys_global_uni_render_list.xml` 里桌面那一项改成 `enable="0"`，让桌面自己画。见下文。 |
| `camera_sdk` | 相机在 PMX110 之外的固件上运行。和 `camera` 移植一样把 ODM 相机配置、`libOplusSecurity.so` 和虚拟录像档位烤进 vendor；相机 SDK 则按类名和方法名打补丁，见 [coloros_camera_sdk.py](../scripts/coloros_camera_sdk.py)。见下文。 |

`flat_display` 不能直接删掉框架的显示 overlay，它里面带着色彩模式列表。删掉后 OPlus 的色彩模式服务仍会设模式 301，抛出 `Invalid colorMode: 301`，`system_server` 崩溃循环。

## 添加一个固件

1. 计算 OTA 的 SHA-256，用 `payload-dumper-go` 提取需要的分区。
2. 对照现有补丁的输入逐个核对：哈希是否相同、文件是否存在。不存在的移植不要加进 `ports`；哈希不同的补丁要重新审计偏移后再写进 `native`。
3. 在 `FIRMWARE` 里加一项。拿不准的能力宁可不加，让它保持原文件。
4. 用 `--workspace`、`--partitions`、`--name`、`--port` 在独立工作区构建，不覆盖已有实例：

```sh
python3 scripts/build_coloros.py --zip /path/to/ota.zip \
  --workspace work/candidate --partitions work/candidate/input/partitions \
  --name ColorOS17_Candidate --port 5576
```

5. 冷启动后检查 `system_server` 是否稳定、桌面图标和壁纸是否显示。`adb screencap` 抓不到圆角遮罩这类 SystemUI 覆盖层，显示效果要看模拟器窗口。画面异常时先查宿主机的模拟器日志（工作区 `logs/emulator-current.log`）里有没有 `mvk-error`，MoltenVK 转换着色器失败只记在那里，客户机的 logcat 里没有。
6. 相机：固件的相机 SDK 和 PMX110 不同时，用 `camera_sdk` 而不是 `camera`。把 `my_product/product_overlay/framework/com.oplus.camera.unit.sdk.jar` 里 `classes.dex` 的 SHA-256 和每处修改的数量登记到 [coloros_camera_sdk.py](../scripts/coloros_camera_sdk.py) 的 `EXPECTED_EDITS`；数量不符时构建会停下，说明 SDK 结构变了，要先对照 `PatchCameraSdk.java` 重新确认。之后在模拟器里实测后摄、前摄拍照和录像。

## PLK110（OnePlus 15）

固件：`PLK110_17.0.0.105(CN01)`，高通平台。

已验证：能开机到桌面，ADB、KernelSU Root、SELinux Enforcing，桌面图标、视频壁纸、设置正常，窗口里没有圆角和挖孔。

没有做：AOD、双击亮屏、蓝牙 HDT 补丁。联发科图形库在这个固件里不存在，AOD 的 DEX 补丁偏移全部不同。

相机（`camera_sdk`）：后摄、前摄拍照和后摄录像可用，照片带 EXIF 方向。录像没有声音：相机 APK 判断不到麦克风，PMX110 靠 APK 补丁解决，这个固件的 APK 类名不同，没有移植。人像等依赖 ISP 的模式也没有处理。

相机要的改动和原因：

- ODM 相机配置要烤进 vendor，否则相机启动就因为缺配置崩溃。
- `libOplusSecurity.so` 要放进 vendor 的 `lib64`。加密的相机配置靠它解密，sphal 命名空间不搜 `/odm/lib64`。解密失败时 `aps_mode` 读成 0，预览没有元数据，画面全黑。
- `camera_unit_config` 的平台改成 `mtk`。PLK110 写的是 `qcom`，SDK 走高通路径，拍照时读取 Ranchu 没有的 vendor tag `com.oplus.sensor.timestamp`，相机崩溃。
- 虚拟录像档位（`media_profiles_V1_0.xml`），否则进录像模式就因为没有 1080p 档位崩溃。
- 相机 SDK 八处修改：去掉主线程等待厂商回调（`ready`），走软件 APS（`aps_mode`），按相机 ID 定类型（`camera_type`），可选厂商数组置空（`capture_metadata`），按步长复制 YUV（`yuv`，否则照片颜色错乱），写 EXIF 方向（`jpeg_orientation`），按请求标签定前后摄（`preview_camera_id`，否则前摄拍不了），重定向曝光补偿步长（`ae_compensation`，Ranchu 虚拟后摄上报 1/2 步长导致专业模式 EV 滑条在 `HSPanelContainer` 中步长除以 0 死循环，重定向为 1/6 与 [-24, 24] 范围）。逐个去掉验证过，`camera_type`、`capture_metadata`、`ready`、`aps_mode`、`ae_compensation` 少一个就拍不了或死循环；PMX110 补丁里的权限判断和 ALog 两处在这里不需要。

卡死问题：在桌面划进负一屏、下拉搜索或下拉控制中心，SurfaceFlinger 的渲染线程会占满一个核，`system_server` 随后被 Watchdog 杀掉重启，严重时客户机整机重启。调用栈显示卡在 Vulkan 队列提交后的同步等待：

```
GaneshVkRenderEngineImpl::flushAndSubmit → vulkan::driver::QueueSubmit
  → ResourceTracker::on_vkQueueSubmit → VkEncoder::vkQueueWaitIdle
  → goldfish_pipe_read（宿主机没有回应，客户机内核里不停重试）
```

定位过程：

| 配置 | 同样的压力测试 |
| --- | --- |
| 宿主 GPU（MoltenVK），不加参数 | 每次都触发，第 1 到 4 轮 |
| 软件 Vulkan（`-gpu lavapipe`） | 6 轮没有卡死 |
| 宿主 GPU，`-feature -VulkanQueueSubmitWithCommands` | 累计 41 轮没有卡死，SurfaceFlinger 没有 abort |

压力测试每轮包括：向右、向左划负一屏，下拉搜索，下拉控制中心。所以卡死出在宿主机 Vulkan 路径上的"带命令的队列提交"，PLK110 的配置因此关闭这个特性。已经排除的因素：OPlus UniRender 合成、`persist.sys.renderengine.retry`、窗口模糊。

这个修复有边界：
- 压力测试是间歇性触发的，累计 41 轮没有再卡死是强证据，不是证明。
- 另外两个带 `-VulkanVirtualQueue` 的配置没有跑到测试（桌面没有出现），这一项没有结论。
- 开机早期 SurfaceFlinger 偶尔会因 `Could not initialize Vulkan RenderEngine!` abort 一次，init 重新拉起后恢复，Zygote 跟着重启一次。不加这个参数的基线开机同样出现过（3 次里 1 次），与这个参数无关。
- 带参数的 4 次冷启动里有 1 次开机用了 145 秒才完成（其余约 28 秒），原因没有查到，内核日志里没有 SurfaceFlinger、Zygote 退出或 Watchdog 记录。

桌面图标空白：PLK110 的名单 `sys_global_uni_render_list.xml` 给桌面开了 OPlus UniRender（开机后是 `sys.unirender.com.android.launcher.enable=1`，桌面日志里是 `[ALTAIR] ... enabled=1`）。开了以后，桌面把图标位图交给 SurfaceFlinger 去画。SurfaceFlinger 走 Vulkan，在 macOS 上由 MoltenVK 转成 Metal，PLK110 的着色器转换失败，模拟器日志里有 `SPIR-V to MSL conversion error: Unknown storage class used for copying arrays` 和大量 `Fragment shader function could not be compiled into pipeline`，图标就空了。联发科对照版的名单同样开着桌面，但它的日志里没有这两种错误，图标正常。

只关掉桌面的 UniRender、HWUI 保持 `skiagl` 后，桌面图标、控制中心毛玻璃和桌面时钟的玻璃效果都正常。之前试过全局 `skiavk`：图标能出来，但控制中心是黑的，时钟也变成深灰色，所以不用这个办法。
