#include "../../native/camera_zoom.h"
#include <cassert>
#include <limits>
#include <iostream>

int main() {
    using namespace avd_camera;
    const auto crop = center_crop(16, 12, 2);
    assert(crop.left == 4 && crop.top == 2 && crop.width == 8 && crop.height == 6);
    assert(center_crop(16, 12, std::numeric_limits<float>::quiet_NaN()).width == 16);
    assert(center_crop(16, 12, 100).width == 4);
    std::vector<uint8_t> scratch;
    const int width = 16, height = 12, stride = 20;
    std::vector<uint8_t> plane(stride * height, 0xee);
    for (int y = 0; y < height; ++y)
        for (int x = 0; x < width; ++x) plane[y * stride + x] = y * width + x;
    zoom_plane(plane.data(), stride, 1, width, height, crop, scratch);
    assert(plane[0] == 36 && plane[15] == 43);
    assert(plane[(height - 1) * stride] == 116);
    for (int y = 0; y < height; ++y)
        for (int x = width; x < stride; ++x) assert(plane[y * stride + x] == 0xee);

    // Interleaved U/V views alias one allocation. Processing U must preserve V.
    std::vector<uint8_t> chroma(20 * 6, 0xee);
    for (int y = 0; y < 6; ++y)
        for (int x = 0; x < 8; ++x) {
            chroma[y * 20 + 2 * x] = y * 8 + x;
            chroma[y * 20 + 2 * x + 1] = 100 + y * 8 + x;
        }
    Crop c{2, 1, 4, 3};
    zoom_plane(chroma.data(), 20, 2, 8, 6, c, scratch);
    assert(chroma[0] == 10 && chroma[1] == 100);
    zoom_plane(chroma.data() + 1, 20, 2, 8, 6, c, scratch);
    assert(chroma[0] == 10 && chroma[1] == 110);
    assert(chroma[14] == 13 && chroma[15] == 113);
    for (int y = 0; y < 6; ++y)
        for (int x = 16; x < 20; ++x) assert(chroma[y * 20 + x] == 0xee);
    std::cout << "PASS: center crop, padded luma, aliased chroma, zoom limits\n";
}
