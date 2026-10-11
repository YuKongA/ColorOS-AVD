# 蜂窝与蓝牙验证

2026-10-11，`ColorOS17_API37` / `emulator-5574`，ColorOS 17.0.0.114，API 36 revision 7 Ranchu Vendor。

## 蜂窝数据

原始镜像的虚拟 T-Mobile SIM 已加载，语音和数据注册均为 `IN_SERVICE` / NR，但没有数据网络请求。ColorOS 的 EthernetTracker 把 Ranchu 无线电使用的 `eth0` 当作独立 Ethernet 接口，启动 DHCP 并注册默认网络。强制请求蜂窝数据后，两个网络代理同时使用 `eth0`，蜂窝数据呼叫成功但未通过联网校验。

构建器新增 `product/overlay/ColorOSConnectivityOverlay/ColorOSConnectivityOverlay.apk`，将 Connectivity 模块的 `config_ethernet_iface_regex` 改为 `usb[0-9]+`，让 EthernetTracker 不再接管 `eth0`。Ranchu Radio HAL、模拟 SIM、移动数据开关及 APN 数据库保留。此 overlay 无应用代码或特权权限，由工作区本地生成的密钥签名，依靠 product 分区的 overlay 策略生效；不关闭 APK 签名验证。

| 检查 | 结果 |
| --- | --- |
| 重建后冷启动 | overlay 自动启用，EthernetTracker 不再跟踪 eth0 |
| Wi-Fi 关闭、移动数据开启 | 默认网络为 `CELLULAR / MOBILE[NR]`，`VALIDATED` |
| 蜂窝 HTTPS | `https://example.com` 返回 200，读取响应首字节成功 |
| 移动数据关闭 | 无默认网络，未留下绕过开关的 Ethernet 网络 |
| 重新开启移动数据 | 默认蜂窝网络恢复，HTTPS 再次返回 200 |
| Wi-Fi 单独连接 AndroidWifi | 默认网络为 WIFI，HTTPS 返回 200 |

最后恢复到 Wi-Fi 关闭、移动数据开启；删除了测试时添加的 AndroidWifi 配置。`mobile_data_always_on` 恢复为原值 0。测试使用 AVD 的虚拟蜂窝网络，经宿主机网络出口访问互联网，没有提供真实 SIM、运营商通话或短信服务。

## 蓝牙

原始镜像开启蓝牙后反复 SIGABRT。Ranchu HCI HAL 已完成 Reset，真正的致命错误在 `libbluetooth_jni.so` 的 `ControllerImpl::impl::read_local_hdt_features_handler`：OPPO 查询控制器专属 HDT 扩展，虚拟控制器的响应不符合该扩展格式，触发 `complete_view.IsValid()` 断言。

对已审核 SHA-256 的原厂库，仅替换该回调入口的 12 字节：保留 ARM64 BTI，清零 `local_hdt_features_` 并返回，表示不支持该扩展。标准 HCI 初始化与数据处理保留。对应汇编为 `native/bluetooth_hdt_compat.S`，输入哈希、原字节和输出哈希由 `native_patches.py` 核验。

| 检查 | 结果 |
| --- | --- |
| 重建后冷启动 | 蓝牙恢复 ON，控制器地址有效 |
| ColorOS 蓝牙设置页 | 显示开启状态与设备名称 |
| 设置页关闭 → 开启 | OFF → ON，调用来自 com.oplus.wirelesssettings |
| 崩溃计数 | 0 |
| Root / SELinux | uid=0 / Enforcing |
| 挂载与文件哈希 | 使用镜像内补丁和 overlay，无临时蓝牙库 bind mount |

验证范围为虚拟控制器初始化及蓝牙开关。设备配对、音频、文件传输和宿主机物理蓝牙设备未验收。临时尝试的蓝牙 simulation 属性已恢复为空，不作为修复依赖。

原始与修复后 dumpsys、崩溃日志、HTTPS 结果、设置页截图和镜像内文件哈希保存在本地 `work/coloros/diagnostics/connectivity/`。相关 Python 编译和 16 项原生补丁、AVD 配置及发布清单测试通过。
