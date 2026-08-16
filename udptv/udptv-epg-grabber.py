"""Build one clean XMLTV guide for the channels in the UDPTV library."""

from __future__ import annotations

import copy
import gzip
import json
import os
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


NAME = "udptv"
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = (15, 240)
USER_AGENT = "UDPTV-EPG-Grabber/3.0"

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR.parent / "epgs"
TVG_IDS_FILE = SCRIPT_DIR / f"{NAME}-tvg-ids.txt"
OUTPUT_FILE = OUTPUT_DIR / f"{NAME}-epg.xml"
OUTPUT_FILE_GZ = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".gz")
REPORT_FILE = OUTPUT_DIR / f"{NAME}-epg-report.json"


@dataclass(frozen=True)
class Source:
    name: str
    url: str


# Ordered by priority. The epg.pw replacements are intentionally first; the
# exported library providers follow; targeted fallbacks for newly mapped
# channels are last. The published UDPTV guide is not downloaded recursively.
SOURCES = (
    Source("epg.pw Movies Now", "https://epg.pw/api/epg.xml?channel_id=543174"),
    Source("epg.pw MNX", "https://epg.pw/api/epg.xml?channel_id=543194"),
    Source("epg.pw MN+", "https://epg.pw/api/epg.xml?channel_id=543209"),
    Source("epg.pw Star Movies HD", "https://epg.pw/api/epg.xml?channel_id=543187"),
    Source(
        "epg.pw Star Movies Select HD",
        "https://epg.pw/api/epg.xml?channel_id=543313",
    ),
    Source("epg.pw Aniplus HD", "https://epg.pw/api/epg.xml?channel_id=491159"),
    Source("epg.pw GMA News TV", "https://epg.pw/api/epg.xml?channel_id=491164"),
    Source("epg.pw DZMM Teleradyo", "https://epg.pw/api/epg.xml?channel_id=464758"),
    Source(
        "Mediaquest Cignal",
        "https://github.com/djdoolky76/Mediaquest-EPG/raw/refs/heads/main/"
        "cignal_epg.xml.gz",
    ),
    Source("EPGShare Canada", "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz"),
    Source(
        "Astro",
        "https://github.com/zultan-m/astro-epg/raw/refs/heads/main/astro.xml.gz",
    ),
    Source("EPGShare India", "https://epgshare01.online/epgshare01/epg_ripper_IN1.xml.gz"),
    Source("StarHub", "http://149.28.153.172:30008/epg/starhub"),
    Source("EPGShare UK", "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz"),
    Source("EPGShare US", "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz"),
    Source(
        "EPGShare US locals",
        "https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS1.xml.gz",
    ),
    Source("GSAT", "https://gsat.atone77721.workers.dev/gsat.xml"),
    Source(
        "Cignal fallback",
        "https://github.com/atone77721/CIGNAL_EPG/raw/refs/heads/main/"
        "merged_epg.xml.gz",
    ),
    Source("Amazon FAST", "https://amazon.atone77721.workers.dev/amazon.xml"),
    Source("EPGShare Germany", "https://epgshare01.online/epgshare01/epg_ripper_DE1.xml.gz"),
    Source("EPGShare Plex", "https://epgshare01.online/epgshare01/epg_ripper_PLEX1.xml.gz"),
    Source("EPGShare Lithuania", "https://epgshare01.online/epgshare01/epg_ripper_LT1.xml.gz"),
    Source("EPGShare Philippines", "https://epgshare01.online/epgshare01/epg_ripper_PH2.xml.gz"),
    Source("EPGShare Singapore", "https://epgshare01.online/epgshare01/epg_ripper_SG1.xml.gz"),
    Source("EPGShare Ireland", "https://epgshare01.online/epgshare01/epg_ripper_IE1.xml.gz"),
    Source("EPGShare Colombia", "https://epgshare01.online/epgshare01/epg_ripper_CO1.xml.gz"),
)


# Source-specific IDs are rewritten to the exact tvg-id values used by the
# final UDPTV channel library. Exact IDs not listed here pass through unchanged.
SOURCE_ID_ALIASES = {
    "543174": "543174",
    "543194": "MNX.HD.in",
    "543209": "MoviesNowPlus.in",
    "543187": "StarMovies.in",
    "543313": "StarMoviesSelect.in",
    "491159": "ANIPLUS.HD.sg",
    "491164": "GMA.News.TV.hk",
    "464758": "DZMM.Radyo.Patrol.us2",
    "Movies.Now.in": "543174",
    "Movies.Now.HD.in": "543174",
    "MNX.in": "MNX.HD.in",
    "MN+.HD.in": "MoviesNowPlus.in",
    "Star.Movies.in": "StarMovies.in",
    "Star.Movies.Select.HD.in": "StarMoviesSelect.in",
    "Buko.ph": "buko",
    "Tapactionflix.Hd.ph": "TAPACTIONFLIX.ph",
}


class SourceError(RuntimeError):
    """Raised when an EPG source cannot be downloaded or parsed."""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load_target_ids() -> set[str]:
    with TVG_IDS_FILE.open("r", encoding="utf-8") as file:
        return {
            line.strip()
            for line in file
            if line.strip() and not line.lstrip().startswith("#")
        }


def map_source_id(source_id: str, target_ids: set[str]) -> str | None:
    if source_id in SOURCE_ID_ALIASES:
        target_id = SOURCE_ID_ALIASES[source_id]
        return target_id if target_id in target_ids else None
    if source_id in target_ids:
        return source_id
    stripped = source_id.strip()
    return stripped if stripped in target_ids else None


def parse_stream(
    stream: object, target_ids: set[str]
) -> tuple[dict[str, ET.Element], dict[str, list[ET.Element]]]:
    channels: dict[str, ET.Element] = {}
    programmes: dict[str, list[ET.Element]] = defaultdict(list)
    context = ET.iterparse(stream, events=("start", "end"))

    try:
        event, root = next(context)
    except StopIteration as exc:
        raise SourceError("empty response") from exc
    if event != "start" or local_name(root.tag) != "tv":
        raise SourceError(f"unexpected root element <{local_name(root.tag)}>")

    for event, element in context:
        if event != "end":
            continue
        tag = local_name(element.tag)
        if tag == "channel":
            target_id = map_source_id(element.get("id", ""), target_ids)
            if target_id is not None:
                channel = copy.deepcopy(element)
                channel.set("id", target_id)
                channels.setdefault(target_id, channel)
            root.clear()
        elif tag == "programme":
            target_id = map_source_id(element.get("channel", ""), target_ids)
            title = element.find("title")
            if (
                target_id is not None
                and element.get("start")
                and title is not None
                and (title.text or "").strip()
            ):
                programme = copy.deepcopy(element)
                programme.set("channel", target_id)
                programmes[target_id].append(programme)
            root.clear()

    return channels, dict(programmes)


def download_source(
    session: requests.Session, source: Source, target_ids: set[str]
) -> tuple[dict[str, ET.Element], dict[str, list[ET.Element]]]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with session.get(
                source.url, stream=True, timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                # Decode transport-level gzip. A URL ending in .gz still needs
                # one additional gzip layer for the file itself.
                response.raw.decode_content = True
                path = urllib.parse.urlsplit(response.url).path.lower()
                if path.endswith(".gz"):
                    with gzip.GzipFile(fileobj=response.raw) as stream:
                        channels, programmes = parse_stream(stream, target_ids)
                else:
                    channels, programmes = parse_stream(response.raw, target_ids)
                if source.name.startswith("epg.pw"):
                    for channel in channels.values():
                        for display_name in channel.findall("display-name"):
                            display_name.set("lang", "en")
                    for entries in programmes.values():
                        for programme in entries:
                            for tag in ("title", "sub-title", "desc"):
                                for element in programme.findall(tag):
                                    element.set("lang", "en")
                return channels, programmes
        except (
            requests.RequestException,
            OSError,
            ET.ParseError,
            SourceError,
        ) as exc:
            last_error = exc
            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS} failed for {source.name}: {exc}"
            )
            if (
                isinstance(exc, requests.HTTPError)
                and exc.response is not None
                and 400 <= exc.response.status_code < 500
                and exc.response.status_code != 429
            ):
                break
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise SourceError(str(last_error or "unknown error"))


def programme_key(programme: ET.Element) -> tuple[str, str, str]:
    return (
        programme.get("start", ""),
        programme.get("stop", ""),
        programme.findtext("title", default=""),
    )


def clean_programmes(programmes: list[ET.Element]) -> list[ET.Element]:
    result: list[ET.Element] = []
    seen: set[tuple[str, str, str]] = set()
    for programme in sorted(programmes, key=lambda item: item.get("start", "")):
        key = programme_key(programme)
        if key not in seen:
            seen.add(key)
            result.append(programme)
    return result


def xmltv_datetime(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M %z", "%Y%m%d%H%M%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def load_previous_output(
    missing_ids: set[str], cutoff: datetime
) -> tuple[dict[str, ET.Element], dict[str, list[ET.Element]]]:
    if not OUTPUT_FILE.exists() or not missing_ids:
        return {}, {}
    try:
        root = ET.parse(OUTPUT_FILE).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"Could not read previous output fallback: {exc}")
        return {}, {}

    channels = {
        channel.get("id", ""): copy.deepcopy(channel)
        for channel in root.findall("channel")
        if channel.get("id", "") in missing_ids
    }
    programmes: dict[str, list[ET.Element]] = defaultdict(list)
    for programme in root.findall("programme"):
        target_id = programme.get("channel", "")
        if target_id not in missing_ids:
            continue
        end = xmltv_datetime(programme.get("stop") or programme.get("start", ""))
        if end is not None and end >= cutoff:
            programmes[target_id].append(copy.deepcopy(programme))
    return channels, dict(programmes)


def make_channel(target_id: str) -> ET.Element:
    channel = ET.Element("channel", {"id": target_id})
    ET.SubElement(channel, "display-name", {"lang": "en"}).text = target_id
    return channel


def write_tree_atomically(tree: ET.ElementTree, output: Path, compressed: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
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
                    filename="",
                    mode="wb",
                    fileobj=temp_file,
                    compresslevel=9,
                    mtime=0,
                ) as zipped:
                    tree.write(zipped, encoding="utf-8", xml_declaration=True)
            else:
                tree.write(temp_file, encoding="utf-8", xml_declaration=True)
        os.replace(temp_path, output)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def write_report_atomically(report: dict[str, object]) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=REPORT_FILE.parent,
            prefix=f".{REPORT_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(report, temp_file, ensure_ascii=False, indent=2, sort_keys=True)
            temp_file.write("\n")
        os.replace(temp_path, REPORT_FILE)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def build_epg() -> tuple[int, int, int]:
    target_ids = load_target_ids()
    selected_channels: dict[str, ET.Element] = {}
    selected_programmes: dict[str, list[ET.Element]] = {}
    selected_sources: dict[str, str] = {}
    failed_sources: list[str] = []

    with requests.Session() as session:
        session.headers.update(
            {"Accept": "application/xml,text/xml,*/*", "User-Agent": USER_AGENT}
        )
        for source in SOURCES:
            remaining = target_ids - selected_programmes.keys()
            if not remaining:
                break
            print(f"Fetching {source.name}: {source.url}")
            try:
                channels, programmes = download_source(session, source, remaining)
            except SourceError as exc:
                failed_sources.append(source.name)
                print(f"Skipping {source.name}: {exc}")
                continue

            added = 0
            for target_id, entries in programmes.items():
                if target_id in selected_programmes:
                    continue
                cleaned = clean_programmes(entries)
                if not cleaned:
                    continue
                selected_programmes[target_id] = cleaned
                selected_channels[target_id] = channels.get(
                    target_id, make_channel(target_id)
                )
                selected_sources[target_id] = source.name
                added += 1
            print(f"Selected {added} channel(s) from {source.name}")

    # A transient provider outage should not erase still-current data that was
    # published by the previous successful run.
    missing_ids = target_ids - selected_programmes.keys()
    fallback_cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    old_channels, old_programmes = load_previous_output(missing_ids, fallback_cutoff)
    for target_id, entries in old_programmes.items():
        cleaned = clean_programmes(entries)
        if not cleaned:
            continue
        selected_programmes[target_id] = cleaned
        selected_channels[target_id] = old_channels.get(target_id, make_channel(target_id))
        selected_sources[target_id] = "previous published output"

    channel_count = len(selected_channels)
    programme_count = sum(len(items) for items in selected_programmes.values())
    if channel_count < 50 or programme_count < 500:
        raise RuntimeError(
            f"Only {channel_count} channels/{programme_count} programmes were built; "
            "keeping existing outputs"
        )

    generated_at = datetime.now(timezone.utc)
    root = ET.Element(
        "tv",
        {
            "date": generated_at.strftime("%Y%m%d%H%M%S +0000"),
            "generator-info-name": USER_AGENT,
            "generator-info-url": "https://github.com/djdoolky76/UDPTV",
            "source-info-name": "UDPTV consolidated EPG",
        },
    )
    for target_id in sorted(selected_channels, key=str.casefold):
        root.append(selected_channels[target_id])
    for target_id in sorted(selected_programmes, key=str.casefold):
        root.extend(selected_programmes[target_id])

    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    write_tree_atomically(tree, OUTPUT_FILE, compressed=False)
    write_tree_atomically(tree, OUTPUT_FILE_GZ, compressed=True)

    missing_ids = sorted(target_ids - selected_programmes.keys(), key=str.casefold)
    report = {
        "generated_at": generated_at.isoformat(),
        "requested_channel_count": len(target_ids),
        "channels_with_epg_count": channel_count,
        "programme_count": programme_count,
        "channels_without_epg": missing_ids,
        "failed_sources": failed_sources,
        "selected_source_by_channel": dict(sorted(selected_sources.items())),
    }
    write_report_atomically(report)
    return channel_count, programme_count, len(missing_ids)


def main() -> int:
    channel_count, programme_count, missing_count = build_epg()
    print(
        f"Saved {OUTPUT_FILE} and {OUTPUT_FILE_GZ}: {channel_count} channels, "
        f"{programme_count} programmes, {missing_count} requested IDs without data"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
