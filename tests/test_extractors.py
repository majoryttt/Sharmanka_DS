import unittest
from bot.extractors.base import Track
from bot.extractors.yandex import YandexMusicExtractor
from bot.extractors.spotify import SpotifyExtractor


class TestExtractors(unittest.TestCase):
    def test_track_duration_formatting(self):
        t_live = Track(title="Stream", artist="DJ", webpage_url="", duration=0)
        self.assertEqual(t_live.formatted_duration, "🔴 Прямой эфир")

        t_short = Track(title="Pop", artist="Singer", webpage_url="", duration=65)
        self.assertEqual(t_short.formatted_duration, "1:05")

        t_long = Track(title="Opera", artist="Band", webpage_url="", duration=3665)
        self.assertEqual(t_long.formatted_duration, "1:01:05")

    def test_track_display_name(self):
        t1 = Track(title="Numb", artist="Linkin Park", webpage_url="", duration=180)
        self.assertEqual(t1.display_name, "Linkin Park — Numb")

        t2 = Track(title="Linkin Park - In The End", artist="Linkin Park", webpage_url="", duration=180)
        self.assertEqual(t2.display_name, "Linkin Park - In The End")

    def test_yandex_can_handle(self):
        ym = YandexMusicExtractor()
        self.assertTrue(ym.can_handle("https://music.yandex.ru/album/2156822/track/19324673"))
        self.assertTrue(ym.can_handle("https://music.yandex.com/album/2156822"))
        self.assertTrue(ym.can_handle("https://music.yandex.ru/users/yamusic-top/playlists/1076"))
        self.assertTrue(ym.can_handle("https://music.yandex.ru/artist/36800"))
        self.assertTrue(ym.can_handle("https://music.yandex.ru/chart"))
        self.assertTrue(ym.can_handle("ym: Кино Группа крови"))
        self.assertTrue(ym.can_handle("yandex: Сплин Моё сердце"))
        self.assertFalse(ym.can_handle("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertFalse(ym.can_handle("Linkin Park Numb"))

    def test_spotify_can_handle(self):
        sp = SpotifyExtractor()
        self.assertTrue(sp.can_handle("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"))
        self.assertTrue(sp.can_handle("https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3"))
        self.assertTrue(sp.can_handle("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"))
        self.assertFalse(sp.can_handle("https://music.yandex.ru/album/2156822"))
        self.assertFalse(sp.can_handle("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))


if __name__ == "__main__":
    unittest.main()
