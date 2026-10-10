# 工具与缓存

此目录可放置外部工具和离线缓存。编译产物默认写入工作区，不需要手动放到这里。

| 文件                                    | 用途                                   | 来源                      |
| --------------------------------------- | -------------------------------------- | ------------------------- |
| `SetWallpaper.dex`                      | Android `app_process` 壁纸设置辅助程序 | 仓库预置资源              |
| `payload-dumper-go`                     | 首次提取官方 OTA 分区                  | PATH、`~/go/bin` 或本目录 |
| `ksud-aarch64-apple-darwin`             | macOS 上修补 ramdisk                   | KernelSU v3.3.0           |
| `ksud-aarch64-linux-android`            | Android 内初始化 Root                  | KernelSU v3.3.0           |
| `lkm-aarch64-android15-6.6_kernelsu.ko` | KernelSU 内核模块                      | KernelSU v3.3.0           |
| `KernelSU_v3.3.0_32601-release.apk`     | KernelSU 管理器                        | KernelSU v3.3.0           |

KernelSU 缓存先从本目录复制，缺失时自动下载至 `work/coloros/tools/`，并校验 SHA-256。外部工具与缓存不提交 Git；本说明和 `SetWallpaper.dex` 为例外。

OPPO 服务源码位于 `native/`，构建时自动生成到 `work/coloros/work/native-services/`。相机桥接库、Java class/DEX 和构建依赖也生成在 `work/coloros/work/`。
