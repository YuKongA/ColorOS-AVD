# ColorOS AVD 兼容性

项目面向 Apple Silicon Mac。系统来自 OPPO Find X10 Pro Max 的 ColorOS 17.0.0.114（Android 17 / API 37），硬件基底为 API 36 Google Play ARM64 revision 7 的 Ranchu Vendor 和 4 KiB 内核。

## 已有验证范围

- ColorOS 原生桌面、设置、首次开机引导、相册和壁纸。
- ADB、KernelSU v3.3.0 Root、全局 SELinux Enforcing。
- Ranchu GPU 合成与播放音频的兼容补丁。
- 前后摄预览与 JPEG 拍照，部分 720p/1080p H.264 + AAC 录像、后摄数码裁剪、专业模式普通拍照。
- userdata 启动前会核验解密设备上的 ext4 容量、UUID 和挂载身份；当前实例从 6 GiB 扩到 16 GiB 后冷启动仍通过。加密扩容需要完整离线备份和受控来宾验证。

相机各项结果及运行时覆盖差异见 [相机验证记录](coloros-camera-validation.md)。前摄缩放未通过；不提供真实手机的超广角/长焦设备；人像、美颜等硬件依赖能力已关闭。4K/60fps、HDR、夜景算法、RAW 和慢动作没有完整成片验收。

开启模拟器 GPS、无线电或传感器选项，只表示配置虚拟设备，不代表已经验证 OPPO 的定位、蜂窝网络、云服务及真实硬件能力。

## 启动与数据

使用 `Start-ColorOS.command` 执行项目初始化。默认 4 核 / 6 GiB RAM / 16 GiB data；运行多个大型 AVD 时需考虑宿主机内存。启动器保留 userdata 和加密密钥，存储只允许扩大。

旧 userdata 可能包含相机测试时的 bind mount 或覆盖文件；它们与最新镜像组合后的结果需要单独核验。构建和注册检查端口与实例归属，拒绝覆盖其他工作区同名 AVD。

固件修改、AVB flags、ADB 认证与 SELinux 设置见 [完整修改清单](coloros-firmware-changes.md)。
