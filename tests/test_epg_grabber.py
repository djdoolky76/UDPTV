import gzip
import importlib.util
import io
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "udptv" / "udptv-epg-grabber.py"
SPEC = importlib.util.spec_from_file_location("udptv_epg_grabber", SCRIPT)
grabber = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = grabber
SPEC.loader.exec_module(grabber)


EXPECTED = {
    "jiotv.491": "mirrornow.jio",
    "jiotv.151": "moviesnow.jio",
    "jiotv.877": "mnx.jio",
    "jiotv.477": "mnplus.jio",
    "jiotv.1401": "romedynow.jio",
    "jiotv.156": "stargold.jio",
    "jiotv.3096": "stargold2.jio",
    "jiotv.3097": "stargoldromance.jio",
    "jiotv.1113": "stargoldselect.jio",
    "jiotv.3098": "stargoldthrills.jio",
    "jiotv.1104": "starmovies.jio",
    "jiotv.1110": "starmoviesselect.jio",
    "jiotv.762": "sonypixhd.jio",
}


class FakeResponse:
    def __init__(self, content):
        self.raw = io.BytesIO(content)
        self.raw.decode_content = False
        self.url = grabber.JIO_EPG_URL

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class JioMappingTests(unittest.TestCase):
    def test_constants_and_target_file_match_exactly(self):
        self.assertEqual(grabber.JIO_SOURCE_ID_ALIASES, EXPECTED)
        self.assertEqual(grabber.JIO_EPG_IDS, frozenset(EXPECTED.values()))
        self.assertTrue(grabber.JIO_EPG_IDS <= grabber.load_target_ids())
        sources = [source for source in grabber.SOURCES if source.name == "JioTV selected channels"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].url, grabber.JIO_EPG_URL)
        self.assertEqual(sources[0].allowed_ids, grabber.JIO_EPG_IDS)

    def test_stream_keeps_only_allowlisted_jio_channels_and_rewrites_ids(self):
        root = ET.Element("tv")
        for source_id in (*EXPECTED, "jiotv.9999"):
            channel = ET.SubElement(root, "channel", id=source_id)
            ET.SubElement(channel, "display-name", lang="en").text = "Name " + source_id
            programme = ET.SubElement(
                root,
                "programme",
                channel=source_id,
                start="20260904000000 +0530",
                stop="20260904010000 +0530",
            )
            ET.SubElement(programme, "title", lang="en").text = "Programme " + source_id
        response = FakeResponse(gzip.compress(ET.tostring(root)))
        session = FakeSession(response)
        source = grabber.Source("JioTV selected channels", grabber.JIO_EPG_URL, grabber.JIO_EPG_IDS)
        channels, programmes = grabber.download_source(session, source, grabber.JIO_EPG_IDS)

        self.assertEqual(set(channels), set(EXPECTED.values()))
        self.assertEqual(set(programmes), set(EXPECTED.values()))
        self.assertTrue(all(len(entries) == 1 for entries in programmes.values()))
        self.assertEqual({channel.get("id") for channel in channels.values()}, set(EXPECTED.values()))
        self.assertEqual(
            {entry.get("channel") for entries in programmes.values() for entry in entries},
            set(EXPECTED.values()),
        )
        self.assertEqual(session.calls[0][0], grabber.JIO_EPG_URL)

    def test_existing_channel_aliases_remain_unchanged(self):
        targets = grabber.load_target_ids()
        self.assertEqual(grabber.map_source_id("543174", targets), "543174")
        self.assertEqual(grabber.map_source_id("543194", targets), "MNX.HD.in")
        self.assertEqual(grabber.map_source_id("543209", targets), "MoviesNowPlus.in")
        self.assertEqual(grabber.map_source_id("543187", targets), "StarMovies.in")
        self.assertEqual(grabber.map_source_id("543313", targets), "StarMoviesSelect.in")

    def test_non_target_jio_id_is_dropped(self):
        targets = grabber.load_target_ids()
        self.assertIsNone(grabber.map_source_id("jiotv.9999", targets))
        self.assertIsNone(grabber.map_source_id("jiotv.491", targets - {"mirrornow.jio"}))


if __name__ == "__main__":
    unittest.main()
