#include <android/binder_ibinder.h>
#include <android/binder_parcel.h>
#include <android/binder_status.h>
#include <android/log.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

#define TAG "UrccStubHAL"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)

typedef binder_status_t (*fn_AServiceManager_addService)(AIBinder* binder, const char* instance);
typedef void (*fn_ABinderProcess_setThreadPoolMaxThreadCount)(uint32_t numThreads);
typedef void (*fn_ABinderProcess_joinThreadPool)(void);
typedef void (*fn_AIBinder_markVintfStability)(AIBinder* binder);

static const char* kDescriptor = "vendor.oplus.hardware.urcc.IUrcc";
static const char* kInstance = "vendor.oplus.hardware.urcc.IUrcc/default";

static void* onBinderCreate(void* args) {
    return args;
}

static void onBinderDestroy(void* userData) {
}

static binder_status_t onBinderTransact(AIBinder* binder, transaction_code_t code, const AParcel* in, AParcel* out) {
    LOGI("onBinderTransact code=%u received from client", code);
    // Write EX_NONE (0)
    AParcel_writeInt32(out, 0);
    // Write return value 1 (handle or success)
    AParcel_writeInt32(out, 1);
    return STATUS_OK;
}

int main(int argc, char** argv) {
    LOGI("Starting URCC Stub HAL daemon for ColorOS-AVD...");

    void* handle = dlopen("libbinder_ndk.so", RTLD_NOW);
    if (!handle) {
        LOGI("Failed to dlopen libbinder_ndk.so: %s", dlerror());
        return 1;
    }

    auto addService = (fn_AServiceManager_addService)dlsym(handle, "AServiceManager_addService");
    auto setThreads = (fn_ABinderProcess_setThreadPoolMaxThreadCount)dlsym(handle, "ABinderProcess_setThreadPoolMaxThreadCount");
    auto joinPool = (fn_ABinderProcess_joinThreadPool)dlsym(handle, "ABinderProcess_joinThreadPool");
    auto markVintf = (fn_AIBinder_markVintfStability)dlsym(handle, "AIBinder_markVintfStability");

    if (!addService || !setThreads || !joinPool) {
        LOGI("Failed to resolve symbols from libbinder_ndk.so");
        return 1;
    }

    setThreads(4);

    AIBinder_Class* clazz = AIBinder_Class_define(kDescriptor, onBinderCreate, onBinderDestroy, onBinderTransact);
    if (!clazz) {
        LOGI("Failed to define AIBinder_Class");
        return 1;
    }

    AIBinder* binder = AIBinder_new(clazz, nullptr);
    if (!binder) {
        LOGI("Failed to create AIBinder");
        return 1;
    }

    if (markVintf) {
        markVintf(binder);
        LOGI("Marked binder with VINTF stability");
    }

    binder_status_t status = addService(binder, kInstance);
    LOGI("AServiceManager_addService('%s') returned %d", kInstance, status);
    if (status != STATUS_OK) {
        return 1;
    }

    LOGI("URCC Stub HAL daemon running successfully at %s", kInstance);
    joinPool();
    return 0;
}
