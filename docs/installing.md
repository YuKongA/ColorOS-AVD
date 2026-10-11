# 安装与启动 ColorOS

发布包面向 Apple Silicon Mac，包含适配后的固件、空白 16 GiB userdata 和与固件匹配的启动代码。安装发布版无需官方 OTA、JDK、NDK 或自行编译。

## 在线安装

```sh
curl -fsSL https://github.com/YuKongA/ColorOS-AVD/releases/latest/download/install.sh | bash
```

需要 Python 3、Android Studio SDK 的 **Android Emulator / Platform-Tools**，以及 Homebrew `e2fsprogs`。安装向导检查这些工具；SDK 路径内已有 `sdkmanager` 时可安装缺失的 SDK 组件，已安装 Homebrew 时可安装 `e2fsprogs`。无需下载 API 36 系统镜像来运行发布包。

引导脚本从 Latest 获取小型安装器，验证 ZIP 和逐文件 SHA-256，再从当前终端读取安装选项。固件清单固定到对应 Release tag，分卷支持断点续传并校验大小和 SHA-256。固件使用 xz 压缩，Python 直接解压，不需要额外安装 xz。

向导可选择安装目录、AVD 名称、空闲偶数端口、内存、存储和 CPU 核数。默认 **4 核 / 6 GiB RAM / 16 GiB data**，显示为 1272×2772 / 560 dpi。下载和解压时需预留约 20 GiB 宿主机磁盘空间，持续使用和备份需要更多空间；向导会根据实际包大小检查可用空间。

首次安装结束后可立即启动，也可双击安装目录中的 `Start.command`。再次打开该目录的 `Install.command`，可以安装更新、启动、调整资源或卸载。

## 离线安装

从 [GitHub Releases](https://github.com/YuKongA/ColorOS-AVD/releases) 下载安装器 ZIP、`manifest.json` 和所有 `.tar.xz.partNNN` 固件分卷。分卷与 manifest 放在同一目录，解压安装器后执行：

```sh
./Install.command --bundle /path/to/manifest.json
```

非交互安装示例：

```sh
python3 scripts/installer.py install --bundle /path/to/manifest.json \
  --root "$HOME/ColorOS-AVD" --name ColorOS17_API37 --port 5574 \
  --ram 6 --storage 16 --cores 4 --sdk "$HOME/Library/Android/sdk"
```

也可使用 `--release v0.1.0-coloros17-r1` 选择指定发布版，添加 `--start` 安装完成后启动。

## 启动与更新

安装目录的入口：

| 文件 | 用途 |
| --- | --- |
| `Install.command` | 安装向导、更新、资源配置和卸载 |
| `Start.command` | 启动 ColorOS |
| `Setup.command` | 重新注册已有镜像 |
| `Uninstall.command` | 移除 AVD 注册，默认保留数据 |

启动时可传入 `--skip-oobe` 跳过首次开机引导、`--headless` 隐藏窗口、`--kill` 关闭当前实例后重启。直接从 Android Studio 启动不会执行项目的 Root、传感器、壁纸和容量验证初始化。

版本固件与对应启动代码位于 `versions/版本号/`，实例的 userdata 和加密密钥位于 `avd/`。安装更新前需关闭目标模拟器；已有实例会先保存完整数据备份，检查用户数据家族与加密模板，再切换固件。存储只允许增大，保数据降级和跨不兼容固件迁移会被拒绝。

旧加密 userdata 扩容或缺少容量证明时，启动器会先备份，通过临时无窗口实例核验 ext4 容量、UUID 和数据，再启动正常实例。失败后保留备份和现场，不自动用旧数据覆盖运行中的用户数据。

ADB 默认序列号为 `emulator-5574`，自定义端口时相应调整：

```sh
adb -s emulator-5574 shell
adb -s emulator-5574 shell su -W -c id
```

## 卸载

关闭模拟器后，在安装目录执行：

```sh
./Uninstall.command
```

默认仅移除 Android Studio 的 AVD 注册，保留用户数据、固件、下载缓存和备份。执行 `Setup.command` 或再次启动可恢复注册。

同时删除当前实例数据和加密密钥：

```sh
./Uninstall.command --delete-data
```

需输入实例名称确认。卸载器检查注册归属和运行进程，不删除其他实例。确认不再需要固件和备份后，可以手动删除整个独立安装目录；Android SDK 不会被删除。

## 从源码构建

开发者使用仓库根目录的 `Build-ColorOS.command`、`Start-ColorOS.command` 和 `Uninstall-ColorOS.command`。SDK API 36 ARM64 revision 7 系统镜像、NDK、JDK、OTA 及构建工具要求见 [重新构建](rebuilding.md)。根目录 `Setup.command` 仅重新注册源码构建产物，不负责在线安装。
