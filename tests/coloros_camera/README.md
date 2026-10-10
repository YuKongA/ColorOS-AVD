# ColorOS 相机设备测试

`CameraYuvTest.java` 在 Android Runtime 上直接调用镜像里的原厂 SDK 补丁，检查五种平面布局、数组复用、缓冲区位置与四种 EXIF 方向。需先构建并启动 ColorOS。

在项目根目录执行（按本机 SDK 路径调整 `CAMERA_TEST_SDK`）：

```sh
CAMERA_TEST_SDK="$HOME/Library/Android/sdk"
mkdir -p work/coloros/camera-test/classes work/coloros/camera-test/dex
javac --release 8 -Xlint:-options \
  -classpath "$CAMERA_TEST_SDK/platforms/android-36/android.jar" \
  -d work/coloros/camera-test/classes tests/coloros_camera/CameraYuvTest.java
"$CAMERA_TEST_SDK/build-tools/36.0.0/d8" --min-api 35 \
  --output work/coloros/camera-test/dex \
  work/coloros/camera-test/classes/android/media/CameraYuvTest*.class
"$CAMERA_TEST_SDK/platform-tools/adb" -s emulator-5574 push \
  work/coloros/camera-test/dex/classes.dex /data/local/tmp/coloros-camera-test.dex
"$CAMERA_TEST_SDK/platform-tools/adb" -s emulator-5574 shell \
  'su -W -c "CLASSPATH=/data/local/tmp/coloros-camera-test.dex:/product/framework/com.oplus.camera.unit.sdk.jar app_process /system/bin android.media.CameraYuvTest"'
```

正常输出 `PASS: five plane layouts, array reuse, buffer positions, EXIF rotations 0/90/180/270`。这个测试验证图像转换与编码；完整验收还需在原生相机中切换前后摄、各拍照两次，并在原生相册里确认颜色和方向。

## 缩放手势

`CameraGesture.java` 通过具有注入权限的 ADB shell 发送真正的双指手势。普通 `adb shell input swipe` 只有一个触点，不能用来判断双指缩放是否有效。

```sh
mkdir -p work/coloros/camera-test/gesture-classes work/coloros/camera-test/gesture-dex
javac --release 8 -Xlint:-options \
  -classpath "$CAMERA_TEST_SDK/platforms/android-36/android.jar" \
  -d work/coloros/camera-test/gesture-classes tests/coloros_camera/CameraGesture.java
"$CAMERA_TEST_SDK/build-tools/36.0.0/d8" --min-api 28 \
  --output work/coloros/camera-test/gesture-dex \
  work/coloros/camera-test/gesture-classes/CameraGesture.class
"$CAMERA_TEST_SDK/platform-tools/adb" -s emulator-5574 push \
  work/coloros/camera-test/gesture-dex/classes.dex /data/local/tmp/coloros-camera-gesture.dex
"$CAMERA_TEST_SDK/platform-tools/adb" -s emulator-5574 shell \
  'CLASSPATH=/data/local/tmp/coloros-camera-gesture.dex app_process /system/bin CameraGesture 636 1200 100 500'
```

四个参数为中心 X/Y、起始半径和结束半径，使用设备屏幕像素坐标。上述值适用于项目默认的 1272×2772 竖屏；交换最后两个参数可测试缩小。`PASS` 只表示手势注入成功，验收需同时检查倍率 UI、预览视野、`dumpsys media.camera` 中的 `zoomRatio`/`cropRegion` 和成片。

完整设备结果、已知异常和复现步骤见 [2026-10-10 验证报告](../../docs/coloros-camera-validation.md)。
