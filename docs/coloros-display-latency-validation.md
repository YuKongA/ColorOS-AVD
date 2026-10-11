# 熄屏与亮屏延迟验证

2026-10-11，`ColorOS17_API37` / `emulator-5574`，ColorOS 17.0.0.114。

## 原因

SurfaceFlinger 在切换显示电源状态时调用原厂 `libcomposer_ext.so`，查询模拟器没有实现的 MTK Composer HIDL 扩展。`ClientImpl::Init` 查询失败后重试 21 次，每次等待 100 ms，阻塞 SurfaceFlinger 主线程。日志同时出现 `Init can't get Composer Ext, tried(0..20) times` 及耗时约 2.1 秒的 `setPowerMode` Binder 调用。

修复前，SurfaceFlinger 的 `Setting power mode` 到 `Finished setting power mode` 日志测得：亮屏 ON 2127 / 2152 ms，进入 DOZE 2160 ms，进入 DOZE_SUSPEND 2135 ms。一次息屏包含多个状态切换，等待会累计；SystemUI 同时记录过 `Skipped 78 frames`。这说明延迟包含硬件扩展查询阻塞，不能仅归因于模拟器 GPU 或双击识别。

## 适配

固定 SHA-256 的 `system_ext/lib64/libcomposer_ext.so` 中，`0x18ac8` 的 `cbz x8` 原来跳往重试日志与 sleep，现在在服务为空时直接跳到 `0x18eb8` 的已有 `-EHOSTDOWN` 返回。仅修改一条 4 字节指令；服务存在时的初始化路径、临时对象清理、堆栈恢复及正常 HWC 合成保留。

补丁登记于 `scripts/native_patches.py`，对应审核源码 `native/composer_ext_no_retry.S`。构建器将库写入镜像并记录输入/输出哈希，原生补丁测试检查实际 OTA 修改范围，发布预检核对镜像中的库。

## 测量方法

使用原厂 AOD 与同一实例，`input keyevent 223` 正常熄屏、`input keyevent 224` 唤醒。记录连续 logcat，按显示 ID、电源模式匹配 SurfaceFlinger 同步调用开始和结束时间。结果表示显示电源状态调用耗时，不等于包含所有动画的总视觉延迟。

原始日志和对比数据保存在本地 `work/coloros/diagnostics/display-latency/`。缺少 MTK 扩展仍可能打印一次“不存在”的回退日志；消除的是阻塞重试，其他手机专属 HAL 日志不作为本次补丁范围。

## 冷启动结果

镜像重建并保留 userdata 冷启动后，SurfaceFlinger 映射的库路径与镜像一致，SHA-256 为 `8b7561b4e1991383ff2b4faf9e7a5efa78fbac2bc06b01c293e95b3d341abf8c`，全局 SELinux Enforcing。

| 同步显示状态调用 | 修复前 | 修复后三轮 |
| --- | --- | --- |
| ON | 2127 / 2152 ms | <1 / 20 / <1 ms |
| DOZE | 2160 ms | <1 / 6 / 15 ms |
| DOZE_SUSPEND | 2135 ms | 2 / 3 / 2 ms |

日志精度为 1 ms，同一时间戳记为 <1 ms。三轮没有出现原来的重试或 `setPowerMode` 慢调用警告。

从 PowerManager 接收请求到显示状态调用完成，正常熄屏进入 DOZE 为 1233–1267 ms，唤醒为 117–127 ms。熄屏剩余时间对应原厂全景 AOD 流程：三轮日志均记录 `requestSmoothTransitionScreenState ... duration=1100`，主动维持 ON 状态完成过渡。本次没有缩短原厂动画或这段等待；上述时间也不代表全部视觉动画已完成。

原生补丁的 4 项测试、Python 编译、diff 检查与实际镜像发布预检通过。冷启动后复测 AOD/黑屏的单击、双击、关闭开关、禁止手势、慢速点击及滑动后点击，唤醒与拒绝唤醒行为保持正常。原始日志为 `baseline.txt` / `patched.txt`，配对调用耗时为 `timings.json`，镜像及映射校验为 `release-preflight.json` / `cold-library.txt`；手势回归记录位于同级 `double-tap-wake/`。
