# 原厂全景 AOD 验证

2026-10-11，`ColorOS17_API37` / `emulator-5574`，ColorOS 17.0.0.114，Ranchu API 36 revision 7。

## 问题与适配

原始运行实例虽然开启了息屏显示，但全景选项不可见，正常熄屏后显示设备进入 OFF。SystemUI 日志显示 DisplayPanelFeature 查询失败，随后写入 `oplus_keyguard_panoramic_aod_support=0`。框架的 `config_dozeComponent` 为空，DreamManager 没有可绑定的 Doze 服务。

构建器对固定 SHA-256 的原厂 SystemUI APK 做局部修改：保留 AIDL 查询路径，在缺少服务时使用的 HIDL 回退中，仅对查询 217 返回 `[13]`，提供全景、全天及进场保持显示的软件能力；平滑硬件面板切换仍关闭，其余面板查询返回不支持。DEX 长度、方法寄存器、异常处理位置及其他代码不变，输入与输出哈希均检查。保留原厂 Signing Block 的可信系统分区识别机制与相机 APK 适配相同，不关闭全局签名验证。

新增 product 框架资源 overlay，绑定原厂 `com.android.systemui.doze.DozeService`，声明软件 AOD 可用性并提供备用 Doze 亮度。没有安装替代时钟或壁纸应用，也没有提供 OPPO 实体 DisplayPanelFeature HAL。原厂设置页选择、时钟、日期和壁纸渲染保留。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 原厂设置页 | 显示全景息屏与局部息屏选项 |
| 重建镜像冷启动 | AOD overlay 自动启用，原厂 DozeService 可用 |
| 正常熄屏 | PowerManager 进入 Dozing，DreamManager 绑定原厂 DozeService |
| 稳定显示 | display override 进入 DOZE_SUSPEND，保留暗化壁纸、时钟及日期 |
| 持续刷新 | 稳定 AOD 截图中时钟从 16:19 更新为 16:21 |
| 设置页关闭息屏显示 | 开关值变为 0，正常熄屏后进入 Asleep，截图为黑屏 |
| 设置页重新开启 | 开关值变为 1，正常熄屏后恢复 Dozing 与壁纸 AOD |
| 文件与挂载 | 使用镜像内的 SystemUI 和 overlay，临时 APK/目录 bind mount 未保留 |
| 校验 | Python 编译、DEX 元数据与修改范围测试、Signing Block 测试及镜像发布预检通过 |

设置页开关验收使用原厂 UI，熄屏使用 `input keyevent 223`。`cmd power sleep` 会强制跳过 Doze，不能用来判断 AOD 是否正常。原始截图、冷启动/开关 dumpsys、资源 overlay、镜像哈希与发布预检记录保存在本地 `work/coloros/diagnostics/aod/`。

## 范围与限制

这是在虚拟显示器上运行原厂全景 AOD 的软件适配，不具备实体 LTPO 面板的 1 Hz / 低功耗特性。专属 AOD 光感传感器缺失，当前亮度使用软件回退；通知、指纹解锁、其他主题和长时间防烧屏行为尚未完整验收。

启动器已停止强制延长自动熄屏时间。当前实例由旧启动行为留下的永不熄屏值恢复为 30 秒；该调整没有写入启动器作为每次启动强制覆盖的规则。验证没有重置用户数据或壁纸。
