package com.coloros.avd.camera;

import android.hardware.camera2.CameraCharacteristics;
import android.util.Range;
import android.util.Rational;
import android.graphics.Rect;
import android.graphics.YuvImage;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.media.Image;
import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;

/**
 * Software capture helpers that PatchCameraSdk merges into the camera unit SDK.
 *
 * The SDK types are reached by reflection: this class is compiled against the
 * Android SDK only, and the SDK jar ships no class files to compile against.
 */
public final class VirtualCameraSdk {
    // addFrameBuff and the JPEG encode run on the same capture thread.
    private static final ThreadLocal<Integer> ROTATION = new ThreadLocal<>();

    private VirtualCameraSdk() {}
    /**
     * Override camera characteristics that freeze ColorOS pro mode on Ranchu.
     *
     * Ranchu reports 1/2 for the virtualscene camera, which causes an infinite
     * loop in HSPanelContainer (0.333333f / 0.5f truncated to int is 0).
     */
    public static Object getCharacteristic(CameraCharacteristics characteristics, CameraCharacteristics.Key<?> key) {
        if (key != null) {
            String name = key.getName();
            if ("android.control.aeCompensationStep".equals(name)) {
                return new Rational(1, 6);
            }
            if ("android.control.aeCompensationRange".equals(name)) {
                return new Range<Integer>(-24, 24);
            }
        }
        return characteristics == null ? null : characteristics.get(key);
    }


    /** Remember the request's JPEG_ORIENTATION for the next encode on this thread. */
    public static void beginCapture(Object captureParam) {
        ROTATION.set(orientation(captureParam));
    }

    /**
     * Copy a YUV_420_888 image to NV21 (17) or NV12 without padding.
     *
     * The SDK copies plane 2 as interleaved VU. Ranchu also delivers planar
     * I420 and interleaved UV, so read every sample with its own strides.
     */
    public static byte[] yuvWithoutPadding(Image image, int format, byte[] out) {
        if (image == null || image.getFormat() != 35) return null;
        int width = image.getWidth(), height = image.getHeight();
        int size = width * height * 3 / 2;
        if (out == null || out.length < size) out = new byte[size];
        Image.Plane[] planes = image.getPlanes();
        for (int index = 0; index < 3; index++) {
            int w = index == 0 ? width : width / 2, h = index == 0 ? height : height / 2;
            Image.Plane plane = planes[index];
            int rowStride = plane.getRowStride(), pixelStride = plane.getPixelStride();
            ByteBuffer buffer = plane.getBuffer();
            int offset = 0, step = 1;
            if (index != 0) {
                step = 2;
                offset = width * height;
                // NV21 is VU: plane 2 (V) first. NV12 is UV: plane 1 (U) first.
                if (format == 17 ? index == 1 : index == 2) offset++;
            }
            for (int row = 0; row < h; row++) {
                int source = row * rowStride;
                for (int column = 0; column < w; column++) {
                    out[offset] = buffer.get(source);
                    offset += step;
                    source += pixelStride;
                }
            }
        }
        return out;
    }

    /**
     * Encode NV21 to JPEG with the request's JPEG_ORIENTATION in EXIF.
     *
     * The SDK's software path otherwise writes no orientation at all.
     */
    public static byte[] nv21ToJpeg(byte[] nv21, int width, int height) {
        ByteArrayOutputStream jpeg = new ByteArrayOutputStream();
        new YuvImage(nv21, 17, width, height, null).compressToJpeg(new Rect(0, 0, width, height), 95, jpeg);
        byte[] data = jpeg.toByteArray();
        Integer remembered = ROTATION.get();
        ROTATION.remove();
        int rotation = remembered == null ? 0 : remembered;
        if (rotation == 0) return data;
        // OplusExifInterface lives in the SDK itself; it writes the same tag the
        // phone's ISP path writes.
        try {
            Class<?> exif = Class.forName("com.oplus.exif.OplusExifInterface");
            Object writer = exif.getConstructor().newInstance();
            Object value = exif.getMethod("getOrientationValueForRotation", int.class).invoke(null, rotation);
            int tag = exif.getField("TAG_ORIENTATION").getInt(null);
            Object built = exif.getMethod("buildTag", int.class, Object.class).invoke(writer, tag, Integer.valueOf(((Number) value).intValue()));
            for (Method method : exif.getMethods()) {
                if (method.getName().equals("setTag") && method.getParameterCount() == 1) method.invoke(writer, built);
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            exif.getMethod("writeExif", byte[].class, OutputStream.class).invoke(writer, data, output);
            return output.toByteArray();
        } catch (ReflectiveOperationException | RuntimeException e) {
            return data;
        }
    }

    /**
     * Report the logical camera of a preview result as "0" (rear) or "1" (front).
     *
     * The SDK reads the active physical camera ID instead. The emulated front HAL
     * reports physical IDs 4 and 5, and the scene HAL reports none.
     */
    public static String previewCameraId(CaptureResult result) {
        if (result == null) return null;
        try {
            Object tag = result.getRequest().getTag();
            int id = tag.getClass().getField("mRearFrontCameraId").getInt(tag);
            return String.valueOf(id);
        } catch (ReflectiveOperationException | RuntimeException e) {
            return null;
        }
    }

    private static int orientation(Object captureParam) {
        try {
            Object meta = captureParam.getClass().getMethod("getPhysicMeta").invoke(captureParam);
            if (!(meta instanceof CaptureResult)) return 0;
            Integer value = ((CaptureResult) meta).getRequest().get(CaptureRequest.JPEG_ORIENTATION);
            return value == null ? 0 : value;
        } catch (ReflectiveOperationException | RuntimeException e) {
            return 0;
        }
    }
}
