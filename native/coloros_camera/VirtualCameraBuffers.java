package com.coloros.avd.camera;

import android.media.CamcorderProfile;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaRecorder;
import android.media.AudioManager;
import android.media.AudioDeviceInfo;
import android.media.MicrophoneInfo;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.CameraCharacteristics;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.view.Surface;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.util.Collections;
import java.util.ArrayList;
import java.util.List;

/** Adapt the OEM camera's persistent video surface and borrowed NV21 planes. */
public final class VirtualCameraBuffers {
    private static volatile int videoWidth = 1920, videoHeight = 1080;
    public static float digitalZoom(float value) {
        return Float.isNaN(value) ? 1 : Math.max(1, Math.min(4, value));
    }
    public static boolean publishShortcuts(ShortcutManager manager, List<ShortcutInfo> shortcuts) {
        List<ShortcutInfo> available = new ArrayList<>();
        for (ShortcutInfo shortcut : shortcuts) {
            if (!"shortcut_portrait_static".equals(shortcut.getId())) available.add(shortcut);
        }
        // Old APKs already published this entry. Remove it on upgrade too;
        // disable any pinned copy so it cannot launch the unavailable mode.
        List<String> portrait = Collections.singletonList("shortcut_portrait_static");
        manager.disableShortcuts(portrait);
        manager.removeDynamicShortcuts(portrait);
        return manager.addDynamicShortcuts(available);
    }
    public static int featureOverride(String feature) {
        if (feature == null) return -1;
        if ("pref_zoom_key".equals(feature)) return 1;
        // Keep the OEM facing check for front zoom: enabling it on the rear
        // routes discrete buttons to a front-only manager with no instance.
        if ("pref_front_wide_zoom_key".equals(feature)) return 0;
        // These modes rely on the physical ISP. Keep Camera2 preview/capture
        // available, but do not route stored beauty/RAW options into that ISP.
        if (feature.startsWith("func_face_beauty_")
                || feature.contains("beauty")
                || feature.contains("makeup")
                || feature.contains("portrait")
                || "pref_face_beauty_key".equals(feature)
                || "key_support_makeup".equals(feature)
                || "key_support_face_beauty_double_mode_custom".equals(feature)
                || "func_bokeh".equals(feature)
                || "func_face_blur".equals(feature)
                || "pref_dual_camera".equals(feature)
                || "pref_portrait_blur_menu".equals(feature)
                || "pref_raw_control_key".equals(feature)
                || "pref_super_raw_control_key".equals(feature)) return 0;
        return -1;
    }
    public static float maxDigitalZoom(Object cameraInfo) {
        if (cameraInfo == null) return 1;
        try {
            Number maximum = (Number) cameraInfo.getClass()
                .getMethod("get", CameraCharacteristics.Key.class)
                .invoke(cameraInfo, CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM);
            return maximum == null ? 1 : Math.max(1, Math.min(4, maximum.floatValue()));
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Unsupported virtual camera characteristics", e);
        }
    }
    public static int captureStreamOverride(String stream) {
        if ("type_still_capture_jpeg".equals(stream)) return 1;
        if ("type_still_capture_yuv_main".equals(stream)
                || "type_still_capture_yuv_sub".equals(stream)
                || "type_tuning_data_yuv".equals(stream)
                || "type_tuning_data_raw".equals(stream)) return 0;
        return -1;
    }
    public static List<MicrophoneInfo> getMicrophones(AudioManager manager) throws java.io.IOException {
        List<MicrophoneInfo> microphones;
        try {
            microphones = manager.getMicrophones();
        } catch (java.io.IOException e) {
            microphones = Collections.emptyList();
        }
        boolean described = false;
        for (MicrophoneInfo microphone : microphones) {
            if (microphone.getType() == AudioDeviceInfo.TYPE_BUILTIN_MIC) described = true;
        }
        if (!described) {
            // Ranchu exposes a real input route without MicrophoneInfo geometry.
            // Retain the OEM gate, setting it only for an available built-in mic.
            AudioDeviceInfo[] inputs = manager.getDevices(AudioManager.GET_DEVICES_INPUTS);
            android.util.Log.i("AVD-Camera", "microphone descriptions=" + microphones.size() + ", input routes=" + inputs.length);
            for (AudioDeviceInfo device : inputs) {
                android.util.Log.i("AVD-Camera", "input type=" + device.getType());
                if (device.getType() == AudioDeviceInfo.TYPE_BUILTIN_MIC) {
                    try {
                        Class.forName("com.oplus.camera.util.Util").getField("d").setBoolean(null, true);
                    } catch (ReflectiveOperationException e) {
                        throw new IllegalStateException("Unsupported camera microphone gate", e);
                    }
                    break;
                }
            }
        }
        return microphones;
    }
    public static CamcorderProfile getProfile(int camera, int quality) {
        CamcorderProfile profile = CamcorderProfile.get(camera, quality);
        videoWidth = profile.videoFrameWidth;
        videoHeight = profile.videoFrameHeight;
        return profile;
    }
    public static Object getOptionalMetadata(Object result, CaptureResult.Key<?> key) {
        try {
            return result.getClass().getMethod("get", CaptureResult.Key.class).invoke(result, key);
        } catch (java.lang.reflect.InvocationTargetException e) {
            // PanoExifUtil already handles null metadata. Ranchu omits the
            // Oplus digital zoom and equivalent focal length vendor tags.
            if (e.getCause() instanceof IllegalArgumentException) return null;
            throw new IllegalStateException("Cannot read panorama metadata", e.getCause());
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Unsupported panorama capture result", e);
        }
    }
    public static Surface createVideoSurface() {
        Surface surface = MediaCodec.createPersistentInputSurface();
        MediaRecorder warmup = new MediaRecorder();
        try {
            // AOSP persistent surfaces start at 1x1. Prepare a temporary
            // recorder before Camera2 configures the output stream, as in
            // the Android persistent-surface sample. release retains Surface.
            warmup.setVideoSource(MediaRecorder.VideoSource.SURFACE);
            warmup.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            warmup.setVideoEncoder(MediaRecorder.VideoEncoder.H264);
            warmup.setVideoSize(videoWidth, videoHeight);
            warmup.setVideoFrameRate(30);
            warmup.setVideoEncodingBitRate(12000000);
            warmup.setInputSurface(surface);
            warmup.setOutputFile("/dev/null");
            warmup.prepare();
        } catch (java.io.IOException | RuntimeException e) {
            surface.release();
            throw new IllegalStateException("Cannot size virtual camera recording surface", e);
        } finally {
            warmup.release();
        }
        return surface;
    }
    public static Image.Plane[] getNv21Planes(Image image) {
        Image.Plane[] planes = image.getPlanes();
        if (image.getFormat() != 35 || planes.length != 3) return planes;
        int width = image.getWidth(), height = image.getHeight();
        ByteBuffer y = ByteBuffer.allocateDirect(width * height);
        ByteBuffer vu = ByteBuffer.allocateDirect(width * height / 2);
        ByteBuffer sourceY = planes[0].getBuffer().duplicate();
        int rowY = planes[0].getRowStride(), pixelY = planes[0].getPixelStride();
        for (int row = 0; row < height; row++) {
            if (pixelY == 1) {
                sourceY.position(row * rowY);
                sourceY.limit(row * rowY + width);
                y.put(sourceY);
                sourceY.limit(sourceY.capacity());
            } else {
                for (int col = 0; col < width; col++) y.put(sourceY.get(row * rowY + col * pixelY));
            }
        }
        ByteBuffer u = planes[1].getBuffer(), v = planes[2].getBuffer();
        int rowU = planes[1].getRowStride(), rowV = planes[2].getRowStride();
        int pixelU = planes[1].getPixelStride(), pixelV = planes[2].getPixelStride();
        for (int row = 0; row < height / 2; row++) {
            for (int col = 0; col < width / 2; col++) {
                vu.put(v.get(row * rowV + col * pixelV));
                vu.put(u.get(row * rowU + col * pixelU));
            }
        }
        y.flip(); vu.flip();
        ByteBuffer uView = vu.duplicate(); uView.position(1);
        // The panorama worker receives only Y and V ByteBuffers and reads a
        // whole NV21 frame asynchronously. Private direct copies remain alive
        // after Image.close(), and give ArcSoft the full chroma capacity.
        setPlane(planes[0], y, width, 1);
        setPlane(planes[1], uView.slice(), width, 2);
        setPlane(planes[2], vu, width, 2);
        return planes;
    }
    private static void setPlane(Image.Plane plane, ByteBuffer data, int row, int pixel) {
        try {
            Class<?> type = plane.getClass();
            Field buffer = type.getDeclaredField("mBuffer");
            Field rowStride = type.getDeclaredField("mRowStride");
            Field pixelStride = type.getDeclaredField("mPixelStride");
            buffer.setAccessible(true); rowStride.setAccessible(true); pixelStride.setAccessible(true);
            buffer.set(plane, data); rowStride.setInt(plane, row); pixelStride.setInt(plane, pixel);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("Unsupported virtual camera Image planes", e);
        }
    }
}
