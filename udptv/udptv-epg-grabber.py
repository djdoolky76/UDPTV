"""Build UDPTV's XMLTV guide from the configured EPG providers."""

from __future__ import annotations

import copy
import gzip
import os
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import requests


NAME = "udptv"
SAVE_AS_GZ = True
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = (15, 60)
USER_AGENT = "UDPTV-EPG-Grabber/2.0"

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR.parent / "epgs"
TVG_IDS_FILE = SCRIPT_DIR / f"{NAME}-tvg-ids.txt"
OUTPUT_FILE = OUTPUT_DIR / f"{NAME}-epg.xml"
OUTPUT_FILE_GZ = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".gz")


@dataclass(frozen=True)
class EpgPwChannel:
    source_id: str
    target_id: str
    display_name: str

    @property
    def url(self) -> str:
        return f"https://epg.pw/api/epg.xml?channel_id={self.source_id}"


# epg.pw uses numeric channel IDs. target_id must match the tvg-id used by the
# UDPTV playlist/udptv-tvg-ids.txt so clients can associate guide data with a
# stream. These feeds are processed first and take precedence when available.
EPG_PW_CHANNELS = (
    EpgPwChannel("543174", "MOVIES.NOW.in", "Movies Now"),
    EpgPwChannel("543194", "MNX.in", "MNX"),
    EpgPwChannel("543209", "MoviesNowPlus.in", "MN+"),
    EpgPwChannel("543187", "StarMovies.in", "Star Movies HD"),
    EpgPwChannel("543313", "StarMoviesSelect.in", "Star Movies Select HD"),
    EpgPwChannel("491159", "Aniplus.id", "Aniplus HD"),
    EpgPwChannel("491164", "GMA.News.TV.hk", "GMA News TV"),
    EpgPwChannel("464758", "TELERADYO.ph", "DZMM Teleradyo"),
)


GENERAL_EPG_URLS = (
    "http://m3u4u.com/xml/68m7n4wgg7ajewedy1ge",
    "https://epgshare01.online/epgshare01/epg_ripper_LT1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_PH2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_HR1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_SG1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_ID1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_MY1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_PH1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_PLEX1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_IN4.xml.gz",
    "https://epg.pw/api/epg.xml?lang=en&channel_id=413152",
    "http://epg:epg@tv.ganbaruby23.xyz/xmltv/channels",
)


def fetch_xml(session: requests.Session, url: str) -> ET.Element | None:
    """Fetch an XML/XML.GZ feed with bounded retries and validation."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            content = response.content
            if content.startswith(b"\x1f\x8b"):
                content = gzip.decompress(content)
            root = ET.fromstring(content)
            if root.tag != "tv":
                raise ValueError(f"unexpected root element <{root.tag}>")
            return root
        except (requests.RequestException, OSError, ET.ParseError, ValueError) as exc:
            print(f"Attempt {attempt}/{MAX_ATTEMPTS} failed for {url}: {exc}")
            if (
                isinstance(exc, requests.HTTPError)
                and exc.response is not None
                and 400 <= exc.response.status_code < 500
                and exc.response.status_code != 429
            ):
                break
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(2 ** (attempt - 1), 4))

    print(f"Skipping unavailable feed: {url}")
    return None


def load_valid_tvg_ids() -> set[str]:
    with TVG_IDS_FILE.open("r", encoding="utf-8") as file:
        return {
            line.strip()
            for line in file
            if line.strip() and not line.lstrip().startswith("#")
        }


def make_epg_pw_channel(
    source_root: ET.Element, channel: EpgPwChannel
) -> tuple[ET.Element, list[ET.Element]] | None:
    """Remap one numeric epg.pw feed to UDPTV's public XMLTV ID."""
    source_channel = source_root.find("channel")
    if source_channel is None:
        print(f"No channel metadata returned for {channel.display_name}")
        return None

    output_channel = ET.Element("channel", {"id": channel.target_id})
    ET.SubElement(output_channel, "display-name", {"lang": "en"}).text = (
        channel.display_name
    )
    source_icon = source_channel.find("icon")
    if source_icon is not None and source_icon.get("src", "").strip():
        output_channel.append(copy.deepcopy(source_icon))

    programmes: list[ET.Element] = []
    for source_programme in source_root.findall("programme"):
        programme = copy.deepcopy(source_programme)
        programme.set("channel", channel.target_id)
        title = programme.find("title")
        if title is None or not (title.text or "").strip():
            continue
        # The English endpoint sometimes labels English text as "zh".
        title.set("lang", "en")
        for tag in ("sub-title", "desc"):
            for element in programme.findall(tag):
                element.set("lang", "en")
        programmes.append(programme)

    if not programmes:
        print(f"No programmes returned for {channel.display_name}; using fallback feeds")
        return None
    return output_channel, programmes


def programme_key(programme: ET.Element) -> tuple[str, str, str, str]:
    return (
        programme.get("channel", ""),
        programme.get("start", ""),
        programme.get("stop", ""),
        programme.findtext("title", default=""),
    )


def append_channel(
    root: ET.Element, channel: ET.Element, seen_channel_ids: set[str]
) -> None:
    tvg_id = channel.get("id", "")
    if tvg_id and tvg_id not in seen_channel_ids:
        root.append(channel)
        seen_channel_ids.add(tvg_id)


def append_programme(
    root: ET.Element,
    programme: ET.Element,
    seen_programmes: set[tuple[str, str, str, str]],
) -> None:
    key = programme_key(programme)
    if key not in seen_programmes:
        root.append(programme)
        seen_programmes.add(key)


def write_tree_atomically(tree: ET.ElementTree, output: Path, compressed: bool) -> None:
    """Replace an output only after its complete new contents are written."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            if compressed:
                with gzip.GzipFile(
                    filename="", mode="wb", fileobj=temp_file, mtime=0
                ) as zipped:
                    tree.write(zipped, encoding="utf-8", xml_declaration=True)
            else:
                tree.write(temp_file, encoding="utf-8", xml_declaration=True)
        os.replace(temp_path, output)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def build_epg() -> tuple[int, int]:
    valid_tvg_ids = load_valid_tvg_ids()
    root = ET.Element(
        "tv",
        {
            "generator-info-name": USER_AGENT,
            "generator-info-url": "https://github.com/djdoolky76/UDPTV",
        },
    )
    seen_channel_ids: set[str] = set()
    seen_programmes: set[tuple[str, str, str, str]] = set()
    preferred_ids: set[str] = set()

    session = requests.Session()
    session.headers.update(
        {"Accept": "application/xml,text/xml,*/*", "User-Agent": USER_AGENT}
    )

    # Fetch preferred replacement feeds first. A failed/empty replacement does
    # not reserve its ID, allowing an older aggregate provider to act as fallback.
    for channel in EPG_PW_CHANNELS:
        if channel.target_id not in valid_tvg_ids:
            raise RuntimeError(
                f"Missing {channel.target_id!r} in {TVG_IDS_FILE.name}"
            )
        print(f"Fetching preferred EPG: {channel.display_name} ({channel.url})")
        source_root = fetch_xml(session, channel.url)
        if source_root is None:
            continue
        mapped = make_epg_pw_channel(source_root, channel)
        if mapped is None:
            continue
        output_channel, programmes = mapped
        append_channel(root, output_channel, seen_channel_ids)
        for programme in programmes:
            append_programme(root, programme, seen_programmes)
        preferred_ids.add(channel.target_id)
        print(f"Added {channel.display_name}: {len(programmes)} programmes")

    # Preserve all of the repository's existing providers and ID filtering.
    for url in GENERAL_EPG_URLS:
        print(f"Fetching XML: {url}")
        source_root = fetch_xml(session, url)
        if source_root is None:
            continue

        for channel in source_root.findall("channel"):
            tvg_id = channel.get("id", "")
            if tvg_id in valid_tvg_ids and tvg_id not in preferred_ids:
                append_channel(root, copy.deepcopy(channel), seen_channel_ids)

        for programme in source_root.findall("programme"):
            tvg_id = programme.get("channel", "")
            if tvg_id in valid_tvg_ids and tvg_id not in preferred_ids:
                append_programme(root, copy.deepcopy(programme), seen_programmes)

    channel_count = len(root.findall("channel"))
    programme_count = len(root.findall("programme"))
    if channel_count == 0 or programme_count == 0:
        raise RuntimeError("No usable EPG data was fetched; keeping existing outputs")

    # XMLTV requires channel declarations before programme entries.
    children = list(root)
    root[:] = sorted(
        children,
        key=lambda element: (
            0 if element.tag == "channel" else 1,
            element.get("id", "")
            if element.tag == "channel"
            else element.get("channel", ""),
            element.get("start", ""),
        ),
    )
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    write_tree_atomically(tree, OUTPUT_FILE, compressed=False)
    if SAVE_AS_GZ:
        write_tree_atomically(tree, OUTPUT_FILE_GZ, compressed=True)

    return channel_count, programme_count


def main() -> int:
    channel_count, programme_count = build_epg()
    print(
        f"Saved {OUTPUT_FILE} and {OUTPUT_FILE_GZ} with "
        f"{channel_count} channels and {programme_count} programmes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
