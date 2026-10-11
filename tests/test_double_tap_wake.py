"""Exercise wake gesture timing and rejection of ordinary/disabled touches."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('c++'), 'Host C++ compiler not installed')
class DoubleTapWakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.work.cleanup)
        cls.binary = Path(cls.work.name) / 'recognizer'
        source = r'''
#include "recognizer.h"
#include <iostream>
int main() {
    DoubleTapRecognizer recognizer;
    int contacts, enabled;
    float x, y;
    int64_t now;
    while (std::cin >> contacts >> x >> y >> now >> enabled)
        std::cout << recognizer.frame(contacts, x, y, now, enabled) << '\n';
}
'''
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-x', 'c++',
                        '-I', str(Path(__file__).resolve().parents[1] / 'native/double_tap_wake'),
                        '-', '-o', str(cls.binary)], input=source, text=True, check=True)

    def results(self, frames):
        result = subprocess.check_output([str(self.binary)], text=True,
                                         input='\n'.join(' '.join(map(str, f)) for f in frames))
        return [int(x) for x in result.split()]

    def taps(self, second=220, enabled=1):
        return [(1, .5, .5, 100, enabled), (0, .5, .5, 160, enabled),
                (1, .5, .5, second, enabled), (0, .5, .5, second + 60, enabled)]

    def test_single_tap_and_double_tap(self):
        self.assertEqual(self.results(self.taps()), [0, 0, 0, 1])

    def test_awake_or_disabled(self):
        self.assertEqual(self.results(self.taps(enabled=0)), [0] * 4)

    def test_taps_too_slow_or_too_fast(self):
        for second in (170, 600):
            self.assertEqual(self.results(self.taps(second)), [0] * 4)

    def test_long_press(self):
        frames = self.taps(second=520)
        frames[1] = (0, .5, .5, 450, 1)
        self.assertEqual(self.results(frames), [0] * 4)

    def test_drag(self):
        frames = self.taps()
        frames.insert(1, (1, .6, .5, 130, 1))
        self.assertEqual(self.results(frames), [0] * 5)

    def test_distant_taps(self):
        frames = self.taps()
        frames[2] = (1, .7, .5, 220, 1)
        frames[3] = (0, .7, .5, 280, 1)
        self.assertEqual(self.results(frames), [0] * 4)

    def test_multitouch_rejects_whole_contact(self):
        frames = self.taps()
        frames.insert(1, (2, .5, .5, 120, 1))
        frames.insert(2, (1, .5, .5, 140, 1))
        self.assertEqual(self.results(frames), [0] * 6)

    def test_switching_policy_cancels_pending_tap(self):
        frames = self.taps()
        frames.insert(2, (0, .5, .5, 180, 0))
        self.assertEqual(self.results(frames), [0] * 5)

    def test_recognizer_recovers_after_rejection(self):
        frames = self.taps(enabled=0) + self.taps(second=600)
        frames[4] = (1, .5, .5, 480, 1)
        frames[5] = (0, .5, .5, 540, 1)
        self.assertEqual(self.results(frames), [0] * 7 + [1])


if __name__ == '__main__':
    unittest.main()
