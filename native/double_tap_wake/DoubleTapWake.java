package com.coloros.avd;

import android.content.Context;
import android.os.Binder;
import android.os.Bundle;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;
import java.lang.reflect.Method;

/** Supplies Android policy to the virtual touchscreen's evdev recognizer. */
public final class DoubleTapWake {
    private static final String TAG = "ColorOSDoubleTap";
    private static PowerManager power;
    private static Method currentUser;
    private static Method wakeUp;
    private static Object activityManager;
    private static Method getProvider;
    private static Method removeProvider;
    private static Method providerCall;
    private static Object provider;
    private static Object attribution;
    private static final Binder token = new Binder();
    private static int providerUser = -1;

    private static native void listen();

    // Called only at contact frames, so idle operation does not poll Binder.
    private static boolean enabled() {
        try {
            if (power.isInteractive()) return false;
            int user = (Integer) currentUser.invoke(null);
            int value = setting("oplus_customize_gesture_double_touch_on", -1, user);
            if (value == -1) value = setting("oplus_customize_gesture_double_touch", 0, user);
            return value == 1 && setting("disable_gestures", 0, user) == 0;
        } catch (Exception error) {
            Log.e(TAG, "Cannot read wake policy", error);
            return false;
        }
    }

    private static int setting(String key, int fallback, int user) throws Exception {
        if (providerUser != user) {
            if (providerUser != -1) removeProvider.invoke(activityManager, "settings", token, providerUser);
            providerUser = -1;
            Object holder = getProvider.invoke(activityManager, "settings", user, token, TAG);
            provider = holder.getClass().getField("provider").get(holder);
            providerUser = user;
        }
        Bundle extras = new Bundle();
        extras.putInt("_user", user);
        Bundle result = (Bundle) providerCall.invoke(provider, attribution,
                "settings", "GET_secure", key, extras);
        String value = result.getString("value");
        return value == null ? fallback : Integer.parseInt(value);
    }

    private static void wake() {
        try {
            if (!enabled()) return;
            // WAKE_REASON_GESTURE, preserving the normal keyguard and AOD exit.
            wakeUp.invoke(power, SystemClock.uptimeMillis(), 4, "ColorOSAVD:double_tap");
            Log.i(TAG, "Double tap woke the display");
        } catch (Exception error) {
            Log.e(TAG, "Cannot wake display", error);
        }
    }

    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        currentUser = Class.forName("android.app.ActivityManager").getMethod("getCurrentUser");
        activityManager = Class.forName("android.app.ActivityManager").getMethod("getService").invoke(null);
        getProvider = Class.forName("android.app.IActivityManager").getMethod("getContentProviderExternal",
                String.class, int.class, android.os.IBinder.class, String.class);
        removeProvider = Class.forName("android.app.IActivityManager").getMethod(
                "removeContentProviderExternalAsUser", String.class, android.os.IBinder.class, int.class);
        Class<?> attributionClass = Class.forName("android.content.AttributionSource");
        Object builder = Class.forName("android.content.AttributionSource$Builder")
                .getConstructor(int.class).newInstance(android.os.Process.myUid());
        attribution = builder.getClass().getMethod("build").invoke(builder);
        providerCall = Class.forName("android.content.IContentProvider").getMethod("call",
                attributionClass, String.class, String.class, String.class, Bundle.class);
        wakeUp = PowerManager.class.getMethod("wakeUp", long.class, int.class, String.class);
        System.load(args[0]);
        listen();
    }
}
