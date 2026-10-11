# 发布 ColorOS 固件

GitHub Release 同时包含固件分卷、冻结运行代码、小型安装器和 `curl | bash` 引导脚本。安装器版本和镜像在同一 tag 下固定，Latest 提供公开入口。

## 准备镜像

使用独立工作区构建最新源码，避免覆盖正在使用的实例：

```sh
ANDROID_AVD_HOME="$PWD/work/coloros-release-r1/registry" \
  python3 scripts/build_coloros.py --workspace "$PWD/work/coloros-release-r1"
```

运行单元测试和独立新装冷启动验收。固件打包器核验打包镜像中的原生补丁、应用删除名单和默认 ADB 认证，重新生成空白 16 GiB userdata，不读取正在使用的个人 userdata。

## 打包

需要宿主机 `xz`：`brew install xz`。

```sh
python3 scripts/package_release.py --workspace work/coloros-release-r1 \
  --version v0.1.0-coloros17-r1 --threads 6
```

输出默认位于 `work/releases/版本号/`。固件使用 xz preset 6，默认按 1536 MiB 分卷，保证每件附件小于 GitHub 的 2 GiB 限制。压缩率和下载包大小与原始稀疏文件的逻辑大小不同。

附件包含：

- `ColorOS-AVD-*.tar.xz.partNNN`：固件、工具、配置及冻结 runtime。
- `manifest.json`：文件大小、SHA-256、权限、来源与用户数据兼容族。
- `ColorOS-AVD-Installer-*.zip`：小型安装向导。
- `installer.json`：安装器 ZIP/文件哈希和固定固件 manifest 哈希。
- `install.sh`：校验安装器后从 `/dev/tty` 进入向导。
- `SHA256SUMS`：所有附件校验和。

## 上传与验收

先创建 Draft 并上传完整附件，核对 Release 附件大小与本地清单，然后发布为 Latest。源码提交和 Release tag 应与附件匹配。不要仅发布分卷或将含个人数据的整个 `work/` 归档。

在线入口依赖公开仓库，私有 Release 不支持匿名 curl 下载：

```sh
curl -fsSL https://github.com/YuKongA/ColorOS-AVD/releases/latest/download/install.sh | bash
```

发布后在独立安装目录检查在线引导、分卷下载校验、安装注册、首次启动、16 GiB data，以及注销和删除数据流程。不要用开发工作区验证卸载。
