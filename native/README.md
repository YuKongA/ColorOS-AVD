# Android 适配源码

此目录保存设备端适配源码及相机 DEX 修改工具，编译输出位于工作区。

| 文件 | 用途 | 构建入口 |
| --- | --- | --- |
| `urcc_service.cpp` | OPPO URCC Binder stub | `scripts/build_coloros.py` |
| `sendextcamcmd_service.cpp` | OPPO 相机扩展命令 Binder stub | `scripts/build_coloros.py` |
| `camera_scene_roles.cpp`、`camera_zoom.h` | Ranchu 相机 metadata 与数码裁剪桥 | `scripts/patch_camera_scene.py` |
| `audio_pcm_recovery.S` | 播放 PCM 的 EIO 恢复补丁源码 | 对应 `scripts/patch_audio.py` 中已固定的机器码 |
| `bluetooth_hdt_compat.S` | 关闭虚拟控制器不支持的 OPPO HDT 扩展 | 对应 `scripts/native_patches.py` 中已固定的机器码 |
| `composer_ext_no_retry.S` | MTK Composer 扩展不存在时直接返回已有错误，避免阻塞屏幕状态切换 | 对应 `scripts/native_patches.py` 中已固定的机器码 |
| `coloros_connectivity/` | 避免 EthernetTracker 接管蜂窝使用的 `eth0` | `scripts/connectivity_overlay.py` |
| `coloros_aod/` | 为原厂 AOD 配置 DozeService 与虚拟显示亮度 | `scripts/resource_overlay.py`、`scripts/coloros_aod.py` |
| `double_tap_wake/` | 虚拟触摸屏熄屏双击识别与原厂开关桥接 | `scripts/double_tap_wake.py` |
| `coloros_camera/VirtualCameraBuffers.java` | Android 相机 buffer、录像 surface 等适配 | `scripts/coloros_camera_buffers.py` |
| `coloros_camera/PatchCameraDex.java` | 宿主机运行的相机 DEX 修改工具 | `scripts/coloros_camera_buffers.py` |

`coloros_camera/` 将同一相机适配的 Java 实现和修改工具放在一起。这里的 Java 文件是源码；class、DEX、APK 和 `.so` 编译产物不写回本目录。
