#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace avd_camera {
struct Crop { int left, top, width, height; };
inline Crop center_crop(int width, int height, float zoom) {
    if (!std::isfinite(zoom)) zoom = 1;
    zoom = std::max(1.0f, std::min(zoom, 4.0f));
    int w = std::max(2, static_cast<int>(width / zoom) & ~1);
    int h = std::max(2, static_cast<int>(height / zoom) & ~1);
    return {(width - w) / 2 & ~1, (height - h) / 2 & ~1, w, h};
}

// Resize samples independently of row/pixel strides; leave padding untouched.
inline void sample_crop(const uint8_t *data, size_t row_stride, size_t pixel_stride,
                        int width, int height, const Crop crop,
                        std::vector<uint8_t> &scratch) {
    scratch.resize(static_cast<size_t>(width) * height);
    for (int y = 0; y < height; ++y) {
        int sy = crop.top + (2 * y + 1) * crop.height / (2 * height);
        for (int x = 0; x < width; ++x) {
            int sx = crop.left + (2 * x + 1) * crop.width / (2 * width);
            scratch[static_cast<size_t>(y) * width + x] =
                data[static_cast<size_t>(sy) * row_stride + sx * pixel_stride];
        }
    }
}
inline void zoom_plane(uint8_t *data, size_t row_stride, size_t pixel_stride,
                       int width, int height, const Crop crop,
                       std::vector<uint8_t> &scratch) {
    sample_crop(data, row_stride, pixel_stride, width, height, crop, scratch);
    for (int y = 0; y < height; ++y)
        for (int x = 0; x < width; ++x)
            data[static_cast<size_t>(y) * row_stride + x * pixel_stride] =
                scratch[static_cast<size_t>(y) * width + x];
}
}
