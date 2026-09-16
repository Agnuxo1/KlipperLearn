import unittest

from klipperlearn.companion import _iter_live_frames


class _Request:
    async def is_disconnected(self):
        return False


class CompanionStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stall_waits_without_replaying_stale_frames(self):
        now = 0.0
        sleeps = 0
        latest = {"jpeg": b"first", "at": 0.0, "seq": 1}

        def clock():
            return now

        async def sleep(_seconds):
            nonlocal now, sleeps
            sleeps += 1
            if sleeps == 1:
                now = 6.0
            elif sleeps == 2:
                now = 10.0
                latest.update(jpeg=b"second", at=now, seq=2)

        stream = _iter_live_frames(_Request(), latest, clock=clock, sleep=sleep)
        first = await anext(stream)
        second = await anext(stream)
        self.assertIn(b"first", first)
        self.assertIn(b"second", second)
        self.assertNotIn(b"first", second)
        self.assertGreaterEqual(sleeps, 2)

    async def test_delete_ends_stream_immediately(self):
        latest = {"jpeg": b"first", "at": 0.0, "seq": 1}

        async def sleep(_seconds):
            latest.update(jpeg=None, at=0.0)

        stream = _iter_live_frames(_Request(), latest, clock=lambda: 0.0, sleep=sleep)
        self.assertIn(b"first", await anext(stream))
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)


if __name__ == "__main__":
    unittest.main()
