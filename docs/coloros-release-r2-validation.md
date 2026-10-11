# ColorOS v0.1.0 / r2 发布验证

2026-10-11，Apple Silicon Mac。固件与冻结运行时代码来自 `c8224b3`；`ead776f` 将后续打包的默认分卷大小改为 1 GiB。本版包含 KernelSU 管理器、原厂壁纸、蜂窝/蓝牙、全景 AOD、双击亮屏和显示状态切换延迟修复，以及安装器的跳过 OOBE 选项。

| 检查 | 结果 |
| --- | --- |
| 构建与预检 | 官方 OTA、原生补丁、指定应用目录裁剪、相机/SystemUI Signing Block、AOD DEX 和双击桥接文件校验通过 |
| 自动测试 | 完整测试 160 项通过 |
| 干净模板 | 打包时新建空白 16 GiB ext4，根目录仅有 `lost+found`，未使用运行实例的数据 |
| 分卷 | 5 个 1 GiB 分卷和一个 159,699,204 bytes 的末卷，压缩内容共 5,528,408,324 bytes |
| 重新分段 | 完整压缩流 SHA-256 前后一致：`526ce1b0e30888cf5e1aed8948f0068c8e94616d6d30a8aec743a7b6213a2a78`；manifest、安装器的 manifest 校验值和 SHA256SUMS 已更新 |
| 最终包新装 | 从最终安装器 ZIP 执行离线安装，解压最终 xz 分卷并逐文件校验通过；QA 注册表、实例名称与端口独立 |
| 跳过 OOBE | 安装时保存选择，生成的 Start.command 带有跳过参数；管理器未显式传参的启动也沿用保存值，首次启动完成并进入桌面 |
| Root 与容量 | uid=0、全局 SELinux Enforcing、ADB 认证和来宾解密 ext4 的 16 GiB 容量核验通过 |
| KernelSU | 系统预装管理器自动安装到 data，原生库提取正常，首次启动管理器进程通过 |
| 全景 AOD | 原厂设置页出现全景入口；通过页面开启并选择全景后，DozeService、壁纸、时钟及 Dozing 状态通过 |
| 双击亮屏 | 单击保持 Dozing，双击从 AOD 和完全黑屏唤醒；关闭原厂开关后黑屏双击不唤醒 |
| 蓝牙 | 虚拟控制器 ON，崩溃计数为 0 |
| 蜂窝 | Wi-Fi 关闭时默认网络为已验证的 CELLULAR，HTTPS 返回 200；关闭移动数据后无默认网络 |
| r1 数据兼容 | userdata family 与加密模板 SHA-256 和 r1 一致；更新仍使用安装器的离线备份与保数据流程 |

新装检查使用隔离的 `ColorOS17_R2_QA` / `emulator-5592`。AOD 首次通过原厂页面配置，待过渡稳定后验收；该测试配置、应用首次使用状态、截图和日志都不进入发布的空白 userdata。蜂窝连接的缓存标签为 LTE，注册服务为 NR，验收依据为默认 CELLULAR 网络的 VALIDATED 状态及实际 HTTPS 响应。

本地记录位于 `work/r2-release/`，包括最终新装的 `qa/validation.json`、AOD 截图和 UI 层级、蓝牙/网络状态、HTTPS 响应、分段哈希以及附件校验记录。显示延迟的前后测量见 [延迟验证](coloros-display-latency-validation.md)，各功能范围见 [兼容性说明](compatibility.md)。

本次未重新验收蓝牙配对/音频、真实 SIM 通话/短信或全部相机模式。全景 AOD 使用软件适配，不提供实体 LTPO 面板低功耗能力。
