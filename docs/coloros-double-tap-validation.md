# 双击亮屏验证

2026-10-11，`ColorOS17_API37` / `emulator-5574`，ColorOS 17.0.0.114。

## 原因与适配

原厂手势 APK 使用 `/proc/touchpanel/double_tap_enable`，Ranchu 没有该驱动节点，Goldfish 传感器列表也没有双击唤醒传感器。原厂开关开启并不意味着虚拟触摸控制器能够产生唤醒事件。

新增主虚拟触摸屏的 evdev 识别桥接。JNI 发现 `virtio_input_multi_touch_1` 并监听完整的多点触摸帧，不使用 EVIOCGRAB；Android 保留正常触摸输入。两次短按各不超过 200 ms，间隔 40–350 ms，位置距离不超过归一化屏幕坐标的 0.08；接触期间移动超过 0.025 或出现多指即取消。输入丢帧时取消手势，并等待已有接触结束。

Java 通过当前用户的原厂 secure 设置判断是否允许唤醒：优先读取 `oplus_customize_gesture_double_touch_on`，缺失时兼容 `oplus_customize_gesture_double_touch`；`disable_gestures=1` 或 PowerManager 处于 interactive 状态时禁止。使用 `PowerManager.wakeUp` 的手势原因，保留锁屏和正常 AOD 退出流程。

构建入口为 `scripts/double_tap_wake.py`，生成系统镜像内的 `ColorOSDoubleTapWake.dex` 与 `libcoloros_double_tap.so`。项目启动器在 KernelSU 和系统就绪后启动 `coloros-double-tap`，发布预检检查这两个文件与构建哈希一致。无需安装手势替代应用或强制打开设置。

## 验证方法

手势测试使用 Emulator console 的 `event mouse`，从虚拟触摸设备经过内核 evdev 输入，与模拟器窗口点击使用相同输入路径。`adb shell input tap` 是框架注入，不经过触摸驱动，不能用于验收此桥接。

正常熄屏使用 `input keyevent 223`；完全黑屏另使用 `cmd power sleep`。记录 PowerManager 唤醒状态及原因、原厂开关、桥接日志和冷启动进程。诊断文件位于本地 `work/coloros/diagnostics/double-tap-wake/`。

宿主机识别器测试覆盖单击、双击、过快/过慢、长按、滑动、远距离双击、多指、开关/亮屏取消及取消后恢复。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 重建镜像、保留 userdata 冷启动 | 启动器自动启动桥接，进程使用镜像内 DEX/JNI |
| AOD 单击 / 双击 | 单击保持 Dozing，双击进入 Awake |
| 完全黑屏单击 / 双击 | 单击保持 Asleep，双击进入 Awake |
| 原厂设置页关闭双击亮屏 | UI 开关变为关闭，secure 值为 0，双击保持 Dozing |
| 原厂设置页重新开启 | UI 开关与 secure 值恢复为 1，双击进入 Awake |
| 禁止手势、慢速两次点击、滑动后点击 | 完全黑屏下均保持 Asleep |
| 唤醒原因 | PowerManager 记录 `mLastWakeReason=4`（GESTURE） |
| Root / SELinux | 桥接运行于 KernelSU 域，全局 Enforcing |
| 自动校验 | 155 项测试、构建、Python 编译、diff 检查及实际镜像发布预检通过 |

原厂开关在验收后恢复为原先的开启状态。运行结果、原厂 UI 层级、PowerManager 快照和发布预检保存在 `cold-validation.json`、`ui-validation.json`、`*-power.txt`、`ui-*.xml` 及 `release-preflight.json`。

## 范围

此适配仅支持 Ranchu 主虚拟触摸屏，不实现实体触摸控制器的低功耗能力、抬起亮屏或其他绘制手势。通过项目启动器初始化，单独绕过启动器运行 emulator 不会自动启动桥接。
