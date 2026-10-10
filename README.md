# ColorOS-AVD

在 Apple Silicon Mac 的 Android Studio ARM64 模拟器中运行 OPPO ColorOS。基于官方 OTA 适配，支持 ADB、KernelSU Root、GPU 加速和 SELinux Enforcing。

## 系统信息

| 项目     | 配置                                                   |
| -------- | ------------------------------------------------------ |
| 系统     | ColorOS 17 / Android 17（API 37）                      |
| 官方固件 | OPPO Find X10 Pro Max / `PMX110_17.0.0.114(CN01)`                              |
| 硬件基底 | API 36 ARM64 revision 7 Ranchu Vendor / 4 KiB GKI 内核 |
| 默认资源 | 4 核 / 6 GiB RAM / 16 GiB 数据分区                     |
| 显示     | 1272 × 2772 / 560 dpi                                  |
| Root     | KernelSU v3.3.0                                        |

原生相机使用虚拟前后摄，支持预览、拍照和录像；实体多摄、人像和美颜不可用。详细能力范围见 [兼容性说明](docs/compatibility.md)。

## 运行截图

<table>
  <tr>
    <td align="center"><img src="screenshots/coloros/home.png" width="220" alt="ColorOS 系统桌面" /><br />系统桌面</td>
    <td align="center"><img src="screenshots/coloros/about.png" width="220" alt="ColorOS 关于本机" /><br />关于本机</td>
    <td align="center"><img src="screenshots/coloros/camera.png" width="220" alt="ColorOS 相机虚拟场景预览" /><br />系统相机</td>
    <td align="center"><img src="screenshots/coloros/gallery.png" width="220" alt="ColorOS 相册查看实拍照片" /><br />系统相册</td>
  </tr>
</table>

## 构建与启动

需要 Apple Silicon Mac、Python 3、JDK、Android Studio SDK 和 Android NDK。SDK 版本及工具准备见 [安装与启动](docs/installing.md)。

```sh
brew install erofs-utils e2fsprogs lz4
```

将配套官方 OTA ZIP 放入 `rom/`，关闭 ColorOS 模拟器后构建：

```sh
python3 scripts/build_coloros.py
```

也可双击 `Build-ColorOS.command`。构建完成后启动：

```sh
./Start-ColorOS.command
```

添加 `--skip-oobe` 可跳过首次开机引导。已有用户数据会保留。

关闭模拟器后，双击 `Uninstall-ColorOS.command` 可移除 AVD 注册并保留数据；删除数据的选项见 [卸载说明](docs/installing.md#卸载)。

连接模拟器或进入 Root shell：

```sh
adb -s emulator-5574 shell
adb -s emulator-5574 shell su -W -c id
```

## 文档

- [安装与启动](docs/installing.md)
- [重新构建](docs/rebuilding.md)
- [兼容性说明](docs/compatibility.md)
- [官方固件修改清单](docs/coloros-firmware-changes.md)

## 致谢

- [HyperOS-AVD](https://github.com/NEORUAA/HyperOS-AVD)
- [Android Emulator / AOSP](https://developer.android.com/studio/run/emulator-commandline)
- [KernelSU](https://github.com/tiann/KernelSU)
- [erofs-utils](https://git.kernel.org/pub/scm/linux/kernel/git/xiang/erofs-utils.git)
