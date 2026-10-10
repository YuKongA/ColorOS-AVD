# 安装与启动 ColorOS

当前项目从官方 OTA 构建 ColorOS，不使用旧项目的在线镜像安装器。

## 环境

- Apple Silicon Mac、Python 3、JDK 17 或更新版本。
- Android Studio SDK：Emulator、Platform-Tools、API 36 Google Play ARM64 系统镜像 **revision 7**。
- SDK platform `android-36`、Build-Tools `36.0.0`、Android NDK，用于编译相机适配代码。
- Homebrew 工具：`brew install erofs-utils e2fsprogs lz4`。
- 首次提取 OTA 时需要 `payload-dumper-go`；可以安装到 PATH，也可以放入 `tools/`。

## 构建

将 OPPO Find X10 Pro Max / PMX110 的 ColorOS 17 官方 OTA ZIP 放入 `rom/`，按 [构建说明](rebuilding.md)准备工具，然后执行：

```sh
python3 scripts/build_coloros.py
```

也可双击根目录的 `Build-ColorOS.command`。默认工作区为 `work/coloros`，构建器会注册 ColorOS AVD。构建前关闭该模拟器，已有 userdata 会保留。

## 启动

双击 `Start-ColorOS.command`，或执行：

```sh
./Start-ColorOS.command
```

可用参数：

- `--skip-oobe`：跳过首次开机引导，打开原生桌面。
- `--kill`：关闭当前 ColorOS 实例后重新启动。
- `--headless`：不显示模拟器窗口。

默认配置为 4 核、6 GiB RAM、16 GiB data、1272×2772 / 560 dpi。启动器会初始化 Root、传感器、壁纸并核验 data 文件系统容量。旧加密实例需要扩容或缺少容量证明时，会先备份到工作区 `backups/`，通过临时无窗口实例完成核验，再正常启动；失败后备份保留，运行中的数据不会自动被旧备份覆盖。直接从 Android Studio 启动不会执行这些初始化步骤。

若镜像已经构建好，只需重新注册路径，可执行 `./Setup.command`。此入口仅注册现有 ColorOS 镜像，不下载或导入其他系统。

ADB 序列号默认为 `emulator-5574`：

```sh
adb -s emulator-5574 shell
adb -s emulator-5574 shell su -W -c id
```

## 卸载

先关闭 ColorOS 模拟器，然后双击 `Uninstall-ColorOS.command` 或执行：

```sh
./Uninstall-ColorOS.command
```

默认移除 Android Studio 中的 AVD 注册信息，保留用户数据、加密密钥、构建镜像和备份。执行 `./Setup.command` 可重新注册；再次使用启动器也会恢复注册。

同时删除当前实例的全部用户数据和加密密钥：

```sh
./Uninstall-ColorOS.command --delete-data
```

此操作要求输入实例名称确认，只删除工作区中对应的 `.avd` 目录，构建镜像和备份继续保留。自定义实例可传入 `--name 实例名称`。

卸载器检查注册归属和运行进程，不会自动关闭模拟器，也不会删除其他工作区或其他实例的数据。不需要 Android SDK 仍然可用。
