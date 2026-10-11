#include "recognizer.h"
#include <android/log.h>
#include <array>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <jni.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

extern "C" JNIEXPORT void JNICALL
Java_com_coloros_avd_DoubleTapWake_listen(JNIEnv* env, jclass cls) {
    auto enabled = env->GetStaticMethodID(cls, "enabled", "()Z");
    auto wake = env->GetStaticMethodID(cls, "wake", "()V");
    // Discover by name, never assume the kernel's event numbering is stable.
    int fd = -1;
    for (int i = 0; i < 64; ++i) {
        char path[64], name[128] = {};
        snprintf(path, sizeof(path), "/dev/input/event%d", i);
        int candidate = open(path, O_RDONLY | O_CLOEXEC);
        if (candidate < 0) continue;
        ioctl(candidate, EVIOCGNAME(sizeof(name)), name);
        if (!strcmp(name, "virtio_input_multi_touch_1")) { fd = candidate; break; }
        close(candidate);
    }
    input_absinfo ax{}, ay{}, slots{};
    int clock = CLOCK_MONOTONIC;
    if (fd < 0 || ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &ax) ||
            ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &ay) ||
            ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &slots) ||
            ioctl(fd, EVIOCSCLOCKID, &clock) || ax.maximum <= ax.minimum ||
            ay.maximum <= ay.minimum || slots.maximum >= 32) {
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),
                "Primary Ranchu touchscreen unavailable");
        if (fd >= 0) close(fd);
        return;
    }
    __android_log_print(ANDROID_LOG_INFO, "ColorOSDoubleTap", "Watching primary virtual touchscreen");
    std::array<bool, 32> active{};
    std::array<int, 32> xs{}, ys{};
    int slot = 0;
    bool dropped = false;
    DoubleTapRecognizer recognizer;
    input_event event{};
    while (true) {
        ssize_t count = read(fd, &event, sizeof(event));
        if (count < 0 && errno == EINTR) continue;
        if (count != sizeof(event)) break;
        if (event.type == EV_SYN && event.code == SYN_DROPPED) {
            // Discard through SYN_REPORT, then reject contacts until release.
            recognizer.reset();
            dropped = true;
            continue;
        }
        if (dropped) {
            if (event.type == EV_SYN && event.code == SYN_REPORT) {
                std::array<int, 33> tracking{};
                tracking[0] = ABS_MT_TRACKING_ID;
                if (ioctl(fd, EVIOCGMTSLOTS(sizeof(tracking)), tracking.data()) < 0) break;
                for (int i = 0; i <= slots.maximum; ++i) active[i] = tracking[i + 1] >= 0;
                recognizer.frame(1, 0, 0, 0, false);
                dropped = false;
            }
            continue;
        }
        if (event.type == EV_ABS) {
            if (event.code == ABS_MT_SLOT) slot = event.value;
            if (slot < 0 || slot > slots.maximum) continue;
            if (event.code == ABS_MT_TRACKING_ID) active[slot] = event.value >= 0;
            if (event.code == ABS_MT_POSITION_X) xs[slot] = event.value;
            if (event.code == ABS_MT_POSITION_Y) ys[slot] = event.value;
        }
        if (event.type != EV_SYN || event.code != SYN_REPORT) continue;
        int contacts = 0, first = 0;
        for (int i = 0; i <= slots.maximum; ++i) if (active[i]) { ++contacts; first = i; }
        float x = float(xs[first] - ax.minimum) / (ax.maximum - ax.minimum);
        float y = float(ys[first] - ay.minimum) / (ay.maximum - ay.minimum);
        int64_t now = int64_t(event.time.tv_sec) * 1000 + event.time.tv_usec / 1000;
        bool allowed = env->CallStaticBooleanMethod(cls, enabled);
        if (env->ExceptionCheck()) break;
        if (recognizer.frame(contacts, x, y, now, allowed)) env->CallStaticVoidMethod(cls, wake);
        if (env->ExceptionCheck()) break;
    }
    close(fd);
    if (!env->ExceptionCheck()) env->ThrowNew(env->FindClass("java/io/IOException"), "Touchscreen read failed");
}
