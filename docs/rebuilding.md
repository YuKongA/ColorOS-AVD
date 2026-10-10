# 重新构建 ColorOS

构建入口为 [build_coloros.py](../scripts/build_coloros.py)，完整固件修改清单见 [ColorOS 固件修改说明](coloros-firmware-changes.md)。

## 输入与工具

默认 OTA 为 `rom/9edada09fc494e0cac8151f3ba336907.zip`，来自 OPPO Find X10 Pro Max / PMX110，ColorOS 17.0.0.114 / Android 17。预期 SHA-256：

```text
9b05a00858b964a3fc5891a1873c91ad38aa4786fb729c1a19748214adb868ae
```

构建器拒绝 SHA-256 不符的 OTA。相机 DEX、Ranchu composer/audio/provider、ColorOS gralloc/GED/HWUI 补丁还会核对对应输入哈希；原生补丁检查原字节和输出哈希。更换固件需先审计并添加匹配规则。

依赖安装见 [安装与启动](installing.md)。KernelSU v3.3.0 工具、android15-6.6 LKM 和管理器缓存到工作区 `tools/`，缺失时自动下载并校验；Python CA 验证失败时可回退到 macOS 系统 HTTPS，证书与域名验证继续启用；根目录 `tools/` 中的同名文件可作为离线缓存。

两个 OPPO stub 服务由 `native/urcc_service.cpp` 和 `native/sendextcamcmd_service.cpp` 自动编译，产物写入工作区 `work/native-services/`，无需在根目录 `tools/` 手动准备服务二进制。需要 NDK 的 ARM64 API 35 编译器。壁纸启动辅助文件为随源码提供的 `tools/SetWallpaper.dex`。

目录约定：`native/` 保存 Android 适配源码，`tools/` 保存外部工具、离线缓存和壁纸 DEX，`scripts/` 保存构建与启动逻辑，`tests/` 保存验证代码；生成的镜像、编译产物、依赖缓存和用户数据位于 `work/coloros/`。

## 构建与产物

```sh
python3 scripts/build_coloros.py
```

使用其他 OTA 路径或独立候选工作区：

```sh
python3 scripts/build_coloros.py --zip /path/to/coloros.zip \
  --workspace /path/to/coloros-candidate \
  --partitions /path/to/coloros-candidate/input/partitions
```

默认工作区 `work/coloros` 包含 `input/partitions`、`work`、`images`、`config`、`local`、`logs` 和 `avd`。官方分区保持为输入，构建后的 AVD 固件写入 `images/`。使用不同候选工作区时需使用独立 AVD 名称或注册表位置，避免同名实例归属冲突。

构建器依次处理分区、属性、Vendor 图形/音频/相机、官方相机 APK/SDK、应用裁剪、KernelSU ramdisk 和 GPT/super 打包。`image_utils.py` 提供 EROFS 读取，`erofs_image.py` 负责保留文件元数据的合并。

构建前关闭使用这些镜像的 ColorOS AVD。已有 `avd/` 用户数据和空白模板不会被重置；新实例使用 16 GiB ext4 模板，旧实例由启动器按配置核验和扩容；磁盘大小与 ext4 超级块容量分别检查，加密扩容先保存完整离线备份，再使用受控来宾验证 UUID 和文件内容。应用删除名单的变化需要重新构建才会进入镜像。

## 验证

```sh
python3 -m unittest discover -s tests
./Start-ColorOS.command
```

检查 ADB、KernelSU Root、SELinux Enforcing、data 容量及桌面。相机设备测试见 [tests/coloros_camera](../tests/coloros_camera/README.md)。普通单元测试不替代重新构建后的完整设备验收。
