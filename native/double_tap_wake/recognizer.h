#pragma once
#include <cmath>
#include <cstdint>

// Coordinates are normalized to 0..1 on the primary virtual touchscreen.
// No EVIOCGRAB: Android continues to receive all ordinary touches.
class DoubleTapRecognizer {
    bool touching_ = false, valid_ = false, previous_ = false;
    int64_t down_ = 0, up_ = 0;
    float x_ = 0, y_ = 0, previous_x_ = 0, previous_y_ = 0;
    static bool near(float x, float y, float a, float b, float slop) {
        return std::hypot(x - a, y - b) <= slop;
    }
public:
    void reset() { touching_ = valid_ = previous_ = false; }
    bool frame(int contacts, float x, float y, int64_t now, bool enabled) {
        if (!enabled || contacts > 1) {
            reset();
            // Keep rejecting the rest of a multi-finger/disabled contact.
            touching_ = contacts > 0;
            return false;
        }
        if (contacts == 1) {
            if (!touching_) {
                touching_ = valid_ = true;
                down_ = now;
                x_ = x; y_ = y;
                if (previous_ && (now - up_ < 40 || now - up_ > 350 ||
                        !near(x, y, previous_x_, previous_y_, 0.08f))) previous_ = false;
            } else if (!near(x, y, x_, y_, 0.025f)) {
                valid_ = previous_ = false;
            }
            return false;
        }
        if (!touching_) return false;
        touching_ = false;
        if (!valid_ || now - down_ > 200 || now < down_) {
            previous_ = false;
            return false;
        }
        if (previous_) {
            reset();
            return true;
        }
        previous_ = true;
        up_ = now;
        previous_x_ = x_; previous_y_ = y_;
        return false;
    }
};
