#include <android/binder_ibinder.h>
#include <android/binder_parcel.h>
#include <android/log.h>
#include <dlfcn.h>

typedef binder_status_t (*AddService)(AIBinder *, const char *);
typedef void (*SetThreads)(uint32_t);
typedef void (*JoinPool)(void);
typedef void (*MarkVintf)(AIBinder *);

static constexpr const char *TAG = "SendExtCamCmdStub";
static constexpr const char *DESCRIPTOR =
        "vendor.oplus.hardware.sendextcamcmd.ISendExtCamCmdService";
static constexpr const char *INSTANCE =
        "vendor.oplus.hardware.sendextcamcmd.ISendExtCamCmdService/default";

static void *create(void *data) { return data; }
static void destroy(void *) {}

static binder_status_t transact(AIBinder *, transaction_code_t code,
                                const AParcel *, AParcel *out) {
    __android_log_print(ANDROID_LOG_INFO, TAG, "transaction %u", code);
    // AIDL replies start with an EX_NONE status.  Most camera extension calls
    // return an integer result; returning success keeps the framework camera
    // client from waiting for a device-only command implementation.
    AParcel_writeInt32(out, 0);
    AParcel_writeInt32(out, 1);
    return STATUS_OK;
}

int main() {
    void *lib = dlopen("libbinder_ndk.so", RTLD_NOW);
    if (!lib) return 1;
    auto add = reinterpret_cast<AddService>(dlsym(lib, "AServiceManager_addService"));
    auto threads = reinterpret_cast<SetThreads>(dlsym(lib, "ABinderProcess_setThreadPoolMaxThreadCount"));
    auto join = reinterpret_cast<JoinPool>(dlsym(lib, "ABinderProcess_joinThreadPool"));
    auto vintf = reinterpret_cast<MarkVintf>(dlsym(lib, "AIBinder_markVintfStability"));
    if (!add || !threads || !join) return 1;
    threads(4);
    auto *clazz = AIBinder_Class_define(DESCRIPTOR, create, destroy, transact);
    auto *binder = clazz ? AIBinder_new(clazz, nullptr) : nullptr;
    if (!binder) return 1;
    if (vintf) vintf(binder);
    binder_status_t status = add(binder, INSTANCE);
    __android_log_print(ANDROID_LOG_INFO, TAG, "registered status=%d", status);
    if (status != STATUS_OK) return 1;
    join();
    return 0;
}
