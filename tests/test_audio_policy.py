from __future__ import annotations

import unittest

from application.audio_policy import AudioTooShortError, validate_meeting_duration


class AudioPolicyTests(unittest.TestCase):
    def test_raises_for_audio_shorter_than_minimum(self) -> None:
        with self.assertRaises(AudioTooShortError):
            validate_meeting_duration(299)

    def test_accepts_audio_at_minimum_duration(self) -> None:
        validate_meeting_duration(300)


if __name__ == "__main__":
    unittest.main()
