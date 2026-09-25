import unittest
from bot.core.queue import MusicQueue, LoopMode
from bot.extractors.base import Track


def create_dummy_track(title: str, artist: str = "Artist", duration: int = 180) -> Track:
    return Track(
        title=title,
        artist=artist,
        webpage_url=f"https://example.com/{title}",
        duration=duration,
        source="test",
        requester="User",
    )


class TestMusicQueue(unittest.TestCase):
    def setUp(self):
        self.queue = MusicQueue()

    def test_add_and_length(self):
        self.assertTrue(self.queue.is_empty)
        t1 = create_dummy_track("Song 1")
        self.queue.add(t1)
        self.assertFalse(self.queue.is_empty)
        self.assertEqual(len(self.queue), 1)

    def test_add_multiple(self):
        tracks = [create_dummy_track(f"Song {i}") for i in range(5)]
        self.queue.add_multiple(tracks)
        self.assertEqual(len(self.queue), 5)
        self.assertEqual(self.queue.total_duration, 5 * 180)

    def test_next_normal_mode(self):
        t1 = create_dummy_track("Song 1")
        t2 = create_dummy_track("Song 2")
        self.queue.add_multiple([t1, t2])

        first = self.queue.next()
        self.assertEqual(first.title, "Song 1")
        self.assertEqual(self.queue.current_track, t1)
        self.assertEqual(len(self.queue), 1)

        second = self.queue.next()
        self.assertEqual(second.title, "Song 2")
        self.assertEqual(len(self.queue), 0)
        self.assertIn(t1, self.queue.history)

        third = self.queue.next()
        self.assertIsNone(third)

    def test_loop_track_mode(self):
        t1 = create_dummy_track("Song 1")
        t2 = create_dummy_track("Song 2")
        self.queue.add_multiple([t1, t2])

        self.queue.next()  # starts Song 1
        self.queue.loop_mode = LoopMode.TRACK

        # In TRACK loop mode, next() should keep repeating the current track
        repeated = self.queue.next()
        self.assertEqual(repeated.title, "Song 1")
        self.assertEqual(len(self.queue), 1)

        # Skip should forcefully move to the next track even in TRACK loop mode
        skipped = self.queue.skip()
        self.assertEqual(skipped.title, "Song 2")

    def test_loop_queue_mode(self):
        t1 = create_dummy_track("Song 1")
        t2 = create_dummy_track("Song 2")
        self.queue.add_multiple([t1, t2])

        self.queue.loop_mode = LoopMode.QUEUE
        first = self.queue.next()
        self.assertEqual(first.title, "Song 1")

        # Now Song 1 should cycle back to end of queue when Song 2 starts
        second = self.queue.next()
        self.assertEqual(second.title, "Song 2")
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(self.queue.tracks[0].title, "Song 1")

    def test_remove_track(self):
        tracks = [create_dummy_track(f"Song {i}") for i in range(1, 4)]
        self.queue.add_multiple(tracks)

        # Remove track at index 2 (Song 2)
        removed = self.queue.remove(2)
        self.assertEqual(removed.title, "Song 2")
        self.assertEqual(len(self.queue), 2)
        self.assertEqual(self.queue.tracks[0].title, "Song 1")
        self.assertEqual(self.queue.tracks[1].title, "Song 3")

    def test_skip_to(self):
        tracks = [create_dummy_track(f"Song {i}") for i in range(1, 6)]
        self.queue.add_multiple(tracks)

        self.queue.next()  # Playing Song 1, queue has [Song 2, Song 3, Song 4, Song 5]
        # skip_to index 3 of waiting queue (Song 4)
        target = self.queue.skip_to(3)
        self.assertEqual(target.title, "Song 4")
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(self.queue.tracks[0].title, "Song 5")

    def test_clear(self):
        tracks = [create_dummy_track(f"Song {i}") for i in range(5)]
        self.queue.add_multiple(tracks)
        cleared_count = self.queue.clear()
        self.assertEqual(cleared_count, 5)
        self.assertTrue(self.queue.is_empty)


if __name__ == "__main__":
    unittest.main()
