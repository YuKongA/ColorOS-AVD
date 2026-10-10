// OEM metadata and zoom bridge for the SHA-256-pinned ARM64 Ranchu scene provider.
#include <__config_site>
#undef _LIBCPP_ABI_NAMESPACE
#define _LIBCPP_ABI_NAMESPACE __1
#include <android/log.h>
#include <camera/NdkCameraMetadataTags.h>
#include <dlfcn.h>
#include <link.h>
#include <sys/mman.h>
#include <unistd.h>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>
#include <atomic>
#include <mutex>
#include <unordered_map>
#include "camera_zoom.h"

// Layouts from camera common/device AIDL V1 and libcamera_metadata, guarded
// by the provider hash in the installer and the relocated function slots here.
struct VendorTag { int32_t id; std::string name; int32_t type; };
struct VendorSection { std::string name; std::vector<VendorTag> tags; };
struct Metadata { std::vector<uint8_t> metadata; };
struct Entry {
    size_t index; uint32_t tag; uint8_t type; size_t count;
    union { const uint8_t *u8; const int32_t *i32; const int64_t *i64; const float *f; const void *raw; } data;
};
struct VendorOps {
    int (*count)(const VendorOps *);
    void (*all)(const VendorOps *, uint32_t *);
    const char *(*section)(const VendorOps *, uint32_t);
    const char *(*name)(const VendorOps *, uint32_t);
    int (*type)(const VendorOps *, uint32_t);
    void *reserved[8];
};
static void (*status_delete)(void *);
static bool (*status_ok)(const void *);
// ScopedAStatus contains one owned AStatus pointer. A nontrivial destructor
// retains its ARM64 indirect-return ABI without depending on private headers.
struct Status {
    void *value;
    Status(Status &&other) noexcept : value(std::exchange(other.value, nullptr)) {}
    ~Status() { if (value) status_delete(value); }
    bool isOk() const { return status_ok(value); }
};
static constexpr uint32_t ROLE = 0x90010000, ROLES = 0x90010001, YUV = 0x90010002,
                          OPLUS_TYPE = 0x90020000;
static Status (*original_tags)(void *, std::vector<VendorSection> *);
static Status (*original_metadata)(void *, Metadata *);
static void *(*allocate_metadata)(size_t, size_t);
static void (*free_metadata)(void *);
static size_t (*metadata_size)(const void *);
static size_t (*entry_count)(const void *);
static size_t (*data_count)(const void *);
static int (*append_metadata)(void *, const void *);
static int (*find_entry)(const void *, uint32_t, Entry *);
static int (*add_entry)(void *, uint32_t, const void *, size_t);
static int (*update_entry)(void *, size_t, const void *, size_t, void *);

struct Bounds { int left, top, right, bottom; };
struct Ycbcr {
    void *y, *cb, *cr;
    size_t ystride, cstride, chroma_step;
    uint32_t reserved[8];
};
static int (*mapper_lock)(void *, const void *, uint32_t, const Bounds &, void **);
static int (*mapper_yuv)(void *, const void *, uint32_t, const Bounds &, Ycbcr *);
static int (*mapper_unlock)(void *, const void *, void *);
static int (*mapper_format)(void *, const void *, int32_t *);
static int (*allocator_allocate)(void *, uint32_t, uint32_t, int32_t, uint32_t,
    uint64_t, const void **, uint32_t *, std::string);
static int (*allocator_free)(void *, const void *);
static std::atomic<float> scene_zoom{1};
static bool scene_zoom_enabled = false;
struct LockedFrame {
    const void *handle = nullptr;
    Ycbcr yuv{};
    uint8_t *rgba = nullptr;
    int width = 0, height = 0;
    float zoom = 1;
};
static thread_local LockedFrame locked_frame;
static thread_local std::vector<uint8_t> zoom_scratch;
static thread_local std::vector<uint8_t> read_shadow[3];
struct CaptureCrop { int width, height; float zoom; };
static std::mutex capture_crops_mutex;
static std::unordered_map<const void *, CaptureCrop> capture_crops;

static int allocate_capture(void *allocator, uint32_t width, uint32_t height,
        int32_t format, uint32_t layers, uint64_t usage, const void **out,
        uint32_t *stride, std::string requestor) {
    bool capture = requestor == "QemuCamera";
    int result = allocator_allocate(allocator, width, height, format, layers,
                                   usage, out, stride, std::move(requestor));
    if (!result && capture && out && *out) {
        std::lock_guard<std::mutex> lock(capture_crops_mutex);
        capture_crops[*out] = {static_cast<int>(width), static_cast<int>(height), scene_zoom.load()};
    }
    return result;
}
static int free_capture(void *allocator, const void *handle) {
    {
        std::lock_guard<std::mutex> lock(capture_crops_mutex);
        capture_crops.erase(handle);
    }
    return allocator_free(allocator, handle);
}
static bool capture_crop(const void *handle, const Bounds &rect, float &zoom) {
    std::lock_guard<std::mutex> lock(capture_crops_mutex);
    auto it = capture_crops.find(handle);
    if (it == capture_crops.end() || it->second.width != rect.right
            || it->second.height != rect.bottom || it->second.zoom <= 1.001f) return false;
    zoom = it->second.zoom;
    return true;
}
static void sample_rgba(const uint8_t *data, int width, int height,
        avd_camera::Crop crop, std::vector<uint8_t> &output) {
    const size_t stride = static_cast<size_t>(width) * 4;
    output.resize(stride * height);
    for (int y = 0; y < height; ++y) {
        int sy = crop.top + (2 * y + 1) * crop.height / (2 * height);
        for (int x = 0; x < width; ++x) {
            int sx = crop.left + (2 * x + 1) * crop.width / (2 * width);
            memcpy(output.data() + y * stride + x * 4, data + sy * stride + sx * 4, 4);
        }
    }
}

static int read_metadata(const void *metadata, uint32_t tag, Entry *entry) {
    if (tag == ACAMERA_SENSOR_EXPOSURE_TIME) {
        Entry ratio{};
        if (!find_entry(metadata, ACAMERA_CONTROL_ZOOM_RATIO, &ratio)
                && ratio.type == 2 && ratio.count == 1 && std::isfinite(ratio.data.f[0]))
            scene_zoom.store(std::max(1.0f, std::min(4.0f, ratio.data.f[0])));
    }
    return find_entry(metadata, tag, entry);
}

static bool crop_dimensions(const Bounds &rect) {
    return rect.left == 0 && rect.top == 0 && rect.right >= 2 && rect.bottom >= 2
        && rect.right <= 4096 && rect.bottom <= 4096
        && !(rect.right & 1) && !(rect.bottom & 1);
}
static int lock_rgba(void *mapper, const void *handle, uint32_t usage,
                     const Bounds &rect, void **pixels) {
    int result = mapper_lock(mapper, handle, usage, rect, pixels);
    int32_t format = 0;
    if (!result && pixels && *pixels && crop_dimensions(rect)
            && !mapper_format(mapper, handle, &format) && (format == 1 || format == 2)) {
        if (usage & 0x30) {
            locked_frame = {handle, {}, static_cast<uint8_t *>(*pixels),
                            rect.right, rect.bottom, scene_zoom.load()};
        } else {
            float zoom;
            if (capture_crop(handle, rect, zoom)) {
                sample_rgba(static_cast<const uint8_t *>(*pixels), rect.right, rect.bottom,
                    avd_camera::center_crop(rect.right, rect.bottom, zoom), read_shadow[0]);
                *pixels = read_shadow[0].data();
            }
        }
    }
    return result;
}
static int lock_yuv(void *mapper, const void *handle, uint32_t usage,
                    const Bounds &rect, Ycbcr *planes) {
    int result = mapper_yuv(mapper, handle, usage, rect, planes);
    if (!result && planes && planes->y && planes->cb && planes->cr
            && crop_dimensions(rect) && planes->ystride >= static_cast<size_t>(rect.right)
            && planes->chroma_step >= 1 && planes->chroma_step <= 2
            && planes->cstride >= static_cast<size_t>(rect.right / 2) * planes->chroma_step) {
        if (usage & 0x30) {
            locked_frame = {handle, *planes, nullptr, rect.right, rect.bottom, scene_zoom.load()};
        } else {
            float zoom;
            if (capture_crop(handle, rect, zoom)) {
                const auto crop = avd_camera::center_crop(rect.right, rect.bottom, zoom);
                const avd_camera::Crop chroma{crop.left / 2, crop.top / 2, crop.width / 2, crop.height / 2};
                avd_camera::sample_crop(static_cast<const uint8_t *>(planes->y), planes->ystride,
                    1, rect.right, rect.bottom, crop, read_shadow[0]);
                avd_camera::sample_crop(static_cast<const uint8_t *>(planes->cb), planes->cstride,
                    planes->chroma_step, rect.right / 2, rect.bottom / 2, chroma, read_shadow[1]);
                avd_camera::sample_crop(static_cast<const uint8_t *>(planes->cr), planes->cstride,
                    planes->chroma_step, rect.right / 2, rect.bottom / 2, chroma, read_shadow[2]);
                planes->y = read_shadow[0].data(); planes->cb = read_shadow[1].data();
                planes->cr = read_shadow[2].data(); planes->ystride = rect.right;
                planes->cstride = rect.right / 2; planes->chroma_step = 1;
            }
        }
    }
    return result;
}
static int unlock_frame(void *mapper, const void *handle, void *fence) {
    auto &frame = locked_frame;
    if (frame.handle == handle) {
        if (frame.zoom > 1.001f) {
            const auto crop = avd_camera::center_crop(frame.width, frame.height, frame.zoom);
            if (frame.rgba) {
                // QemuCamera.queryFrame writes packed RGBA rows.
                sample_rgba(frame.rgba, frame.width, frame.height, crop, zoom_scratch);
                memcpy(frame.rgba, zoom_scratch.data(), zoom_scratch.size());
            } else {
                avd_camera::zoom_plane(static_cast<uint8_t *>(frame.yuv.y), frame.yuv.ystride,
                    1, frame.width, frame.height, crop, zoom_scratch);
                const avd_camera::Crop chroma{crop.left / 2, crop.top / 2, crop.width / 2, crop.height / 2};
                avd_camera::zoom_plane(static_cast<uint8_t *>(frame.yuv.cb), frame.yuv.cstride,
                    frame.yuv.chroma_step, frame.width / 2, frame.height / 2, chroma, zoom_scratch);
                avd_camera::zoom_plane(static_cast<uint8_t *>(frame.yuv.cr), frame.yuv.cstride,
                    frame.yuv.chroma_step, frame.width / 2, frame.height / 2, chroma, zoom_scratch);
            }
        }
        frame = {};
    }
    return mapper_unlock(mapper, handle, fence);
}

static int tag_count(const VendorOps *) { return 4; }
static void tag_all(const VendorOps *, uint32_t *out) {
    out[0] = ROLE; out[1] = ROLES; out[2] = YUV; out[3] = OPLUS_TYPE;
}
static const char *tag_section(const VendorOps *, uint32_t tag) {
    if (tag == ROLE || tag == ROLES) return "com.xiaomi.cameraid.role";
    if (tag == YUV) return "xiaomi.yuv";
    if (tag == OPLUS_TYPE) return "com.oplus.supported.cameraid";
    return nullptr;
}
static const char *tag_name(const VendorOps *, uint32_t tag) {
    if (tag == ROLE) return "cameraId";
    if (tag == ROLES) return "cameraIds";
    if (tag == YUV) return "format";
    if (tag == OPLUS_TYPE) return "type";
    return nullptr;
}
static int tag_type(const VendorOps *, uint32_t tag) {
    return (tag >= ROLE && tag <= YUV) || tag == OPLUS_TYPE ? 1 : -1;
}
static const VendorOps vendor_ops{tag_count, tag_all, tag_section, tag_name, tag_type, {}};

static Status vendor_tags(void *self, std::vector<VendorSection> *out) {
    auto status = original_tags(self, out);
    if (!status.isOk() || !out) return status;
    *out = {{"com.xiaomi.cameraid.role", {{static_cast<int32_t>(ROLE), "cameraId", 1},
                                        {static_cast<int32_t>(ROLES), "cameraIds", 1}}},
            {"xiaomi.yuv", {{static_cast<int32_t>(YUV), "format", 1}}},
            {"com.oplus.supported.cameraid", {{static_cast<int32_t>(OPLUS_TYPE), "type", 1}}}};
    return status;
}

template<class T> static int add_preview_sizes(void *copy, uint32_t tag, uint8_t type) {
    Entry entry{};
    if (find_entry(copy, tag, &entry) || entry.type != type || entry.count % 4 || entry.count > 4096)
        return -1;
    const auto *data = static_cast<const T *>(entry.data.raw);
    std::vector<T> values(data, data + entry.count);
    std::vector<T> formats;
    static const int32_t EXTRA[][2] = {
        {1024, 768},
        {1280, 720},
        {1920, 1080},
        {1440, 1080},
        {1920, 1440}
    };
    for (size_t i = 0; i < entry.count; i += 4) {
        T format = data[i];
        bool known = false;
        for (T previous : formats) if (previous == format) known = true;
        if (known) continue;
        formats.push_back(format);
        for (const auto &sz : EXTRA) {
            bool present = false;
            for (size_t j = 0; j < values.size(); j += 4) {
                if (values[j] == format && values[j + 1] == sz[0] && values[j + 2] == sz[1]) {
                    present = true;
                    break;
                }
            }
            if (!present) values.insert(values.end(), {format, static_cast<T>(sz[0]), static_cast<T>(sz[1]), data[i + 3]});
        }
    }
    return update_entry(copy, entry.index, values.data(), values.size(), nullptr);
}

static Status characteristics(void *self, Metadata *out) {
    auto status = original_metadata(self, out);
    if (!status.isOk() || !out || out->metadata.empty()) return status;
    const void *old = out->metadata.data();
    Entry facing{}, keys{};
    if (find_entry(old, ACAMERA_LENS_FACING, &facing) || facing.count != 1 ||
        facing.type != 0 || facing.data.u8[0] > 1 ||
        find_entry(old, ACAMERA_REQUEST_AVAILABLE_CHARACTERISTICS_KEYS, &keys) ||
        keys.type != 1 || keys.count > 4096) return status;
    std::vector<int32_t> available(keys.data.i32, keys.data.i32 + keys.count);
    available.insert(available.end(), {static_cast<int32_t>(ROLE), static_cast<int32_t>(ROLES),
                                      static_cast<int32_t>(YUV), static_cast<int32_t>(OPLUS_TYPE)});
    void *copy = allocate_metadata(entry_count(old) + 4, data_count(old) + 4096);
    if (!copy) return status;
    int32_t role = facing.data.u8[0] == 0 ? 1 : 0;
    int32_t format = 2; // NV21, matching the existing private YUV plane bridge.
    int32_t oplus_type = facing.data.u8[0] == 0 ? 1 : 0; // 0 = rear_main, 1 = front_main
    int error = append_metadata(copy, old);
    if (!error) error = add_entry(copy, ROLE, &role, 1);
    if (!error) error = add_entry(copy, ROLES, &role, 1);
    if (!error) error = add_entry(copy, YUV, &format, 1);
    if (!error) error = add_entry(copy, OPLUS_TYPE, &oplus_type, 1);
    if (!error) error = update_entry(copy, keys.index, available.data(), available.size(), nullptr);
    // Advertise the renderable sizes selected by Xiaomi and Oplus previews.
    if (!error) error = add_preview_sizes<int32_t>(copy, ACAMERA_SCALER_AVAILABLE_STREAM_CONFIGURATIONS, 1);
    if (!error) error = add_preview_sizes<int64_t>(copy, ACAMERA_SCALER_AVAILABLE_MIN_FRAME_DURATIONS, 3);
    if (!error) error = add_preview_sizes<int64_t>(copy, ACAMERA_SCALER_AVAILABLE_STALL_DURATIONS, 3);
    Entry zoom{}, maximum{};
    const float range[] = {1, 4}, max_zoom = 4;
    if (!error && scene_zoom_enabled && !find_entry(copy, ACAMERA_CONTROL_ZOOM_RATIO_RANGE, &zoom)
            && zoom.type == 2 && zoom.count == 2)
        error = update_entry(copy, zoom.index, range, 2, nullptr);
    if (!error && scene_zoom_enabled && !find_entry(copy, ACAMERA_SCALER_AVAILABLE_MAX_DIGITAL_ZOOM, &maximum)
            && maximum.type == 2 && maximum.count == 1)
        error = update_entry(copy, maximum.index, &max_zoom, 1, nullptr);
    if (!error) {
        size_t size = metadata_size(copy);
        const auto *bytes = static_cast<const uint8_t *>(copy);
        out->metadata.assign(bytes, bytes + size);
    }
    free_metadata(copy);
    __android_log_print(error ? ANDROID_LOG_ERROR : ANDROID_LOG_INFO,
                        "AVD-Camera-Scene", "role=%d metadata result=%d", role, error);
    return status;
}

static int install_hooks(dl_phdr_info *info, size_t, void *) {
    if (info->dlpi_name && *info->dlpi_name &&
        strcmp(info->dlpi_name, "/vendor/bin/hw/android.hardware.camera.provider.ranchu")) return 0;
    uintptr_t base = info->dlpi_addr;
    auto **tags = reinterpret_cast<void **>(base + 0x4c198);
    auto **metadata = reinterpret_cast<void **>(base + 0x4c040);
    if (*tags != reinterpret_cast<void *>(base + 0x2abe0) ||
        *metadata != reinterpret_cast<void *>(base + 0x1c520)) return 1;
#define RESOLVE(variable, symbol) \
    variable = reinterpret_cast<decltype(variable)>(dlsym(RTLD_DEFAULT, symbol)); \
    if (!variable) return 1;
    RESOLVE(allocate_metadata, "allocate_camera_metadata")
    RESOLVE(free_metadata, "free_camera_metadata")
    RESOLVE(metadata_size, "get_camera_metadata_size")
    RESOLVE(entry_count, "get_camera_metadata_entry_count")
    RESOLVE(data_count, "get_camera_metadata_data_count")
    RESOLVE(append_metadata, "append_camera_metadata")
    RESOLVE(find_entry, "find_camera_metadata_ro_entry")
    RESOLVE(add_entry, "add_camera_metadata_entry")
    RESOLVE(update_entry, "update_camera_metadata_entry")
    RESOLVE(status_delete, "AStatus_delete")
    RESOLVE(status_ok, "AStatus_isOk")
#undef RESOLVE
    auto set_ops = reinterpret_cast<int (*)(const VendorOps *)>(
                   dlsym(RTLD_DEFAULT, "set_camera_metadata_vendor_ops"));
    if (!set_ops || set_ops(&vendor_ops)) return 1;
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) return 1;
    uintptr_t address = reinterpret_cast<uintptr_t>(tags) & ~(static_cast<uintptr_t>(page) - 1);
    if ((reinterpret_cast<uintptr_t>(metadata) & ~(static_cast<uintptr_t>(page) - 1)) != address ||
        mprotect(reinterpret_cast<void *>(address), page, PROT_READ | PROT_WRITE)) return 1;
    original_tags = reinterpret_cast<decltype(original_tags)>(*tags);
    original_metadata = reinterpret_cast<decltype(original_metadata)>(*metadata);
    *tags = reinterpret_cast<void *>(vendor_tags);
    *metadata = reinterpret_cast<void *>(characteristics);
    mprotect(reinterpret_cast<void *>(address), page, PROT_READ);
    // Exact GOT offsets and signatures of the hash-guarded API 36 provider.
    // Capture buffers are transformed while CPU_WRITE locks are still held.
    struct Hook { uintptr_t offset; const char *symbol; void *replacement; void **original; };
    Hook hooks[] = {
        {0x4d180, "_ZN7android22GraphicBufferAllocator4freeEPK13native_handle", reinterpret_cast<void *>(free_capture), reinterpret_cast<void **>(&allocator_free)},
        {0x4d458, "find_camera_metadata_ro_entry", reinterpret_cast<void *>(read_metadata), nullptr},
        {0x4d4c8, "_ZN7android19GraphicBufferMapper4lockEPK13native_handlejRKNS_4RectEPPv", reinterpret_cast<void *>(lock_rgba), reinterpret_cast<void **>(&mapper_lock)},
        {0x4d4d0, "_ZN7android19GraphicBufferMapper9lockYCbCrEPK13native_handlejRKNS_4RectEP13android_ycbcr", reinterpret_cast<void *>(lock_yuv), reinterpret_cast<void **>(&mapper_yuv)},
        {0x4d4d8, "_ZN7android19GraphicBufferMapper6unlockEPK13native_handlePNS_4base14unique_fd_implINS4_13DefaultCloserEEE", reinterpret_cast<void *>(unlock_frame), reinterpret_cast<void **>(&mapper_unlock)},
        {0x4d4c0, "_ZN7android22GraphicBufferAllocator8allocateEjjijmPPK13native_handlePjNSt3__112basic_stringIcNS6_11char_traitsIcEENS6_9allocatorIcEEEE", reinterpret_cast<void *>(allocate_capture), reinterpret_cast<void **>(&allocator_allocate)},
    };
    mapper_format = reinterpret_cast<decltype(mapper_format)>(dlsym(RTLD_DEFAULT,
        "_ZN7android19GraphicBufferMapper23getPixelFormatRequestedEPK13native_handlePNS_8hardware8graphics6common4V1_211PixelFormatE"));
    bool verified = mapper_format;
    for (const auto &hook : hooks)
        verified = verified && *reinterpret_cast<void **>(base + hook.offset) == dlsym(RTLD_DEFAULT, hook.symbol);
    uintptr_t got_page = (base + hooks[0].offset) & ~(static_cast<uintptr_t>(page) - 1);
    if (verified && !mprotect(reinterpret_cast<void *>(got_page), page, PROT_READ | PROT_WRITE)) {
        for (const auto &hook : hooks) {
            auto **slot = reinterpret_cast<void **>(base + hook.offset);
            if (hook.original) *hook.original = *slot;
            *slot = hook.replacement;
        }
        mprotect(reinterpret_cast<void *>(got_page), page, PROT_READ);
        scene_zoom_enabled = true;
        __android_log_print(ANDROID_LOG_INFO, "AVD-Camera-Scene", "1x-4x YUV/RGBA crop bridge active");
    }
    __android_log_print(ANDROID_LOG_INFO, "AVD-Camera-Scene", "scene metadata bridge active");
    return 1;
}

__attribute__((constructor)) static void initialize() { dl_iterate_phdr(install_hooks, nullptr); }
