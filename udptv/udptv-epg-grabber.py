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
from zoneinfo import ZoneInfo

import requests


NAME = "udptv"
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = (15, 240)
USER_AGENT = "UDPTV-EPG-Grabber/3.0"
MANILA_TIMEZONE = ZoneInfo("Asia/Manila")
CUSTOM_LOOKBACK_DAYS = 1
CUSTOM_LOOKAHEAD_DAYS = 14

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


ScheduleEntry = tuple[int, int, str]


@dataclass(frozen=True)
class CustomChannel:
    channel_id: str
    display_names: tuple[str, ...]
    source_url: str
    schedule_by_weekday: dict[int, tuple[ScheduleEntry, ...]]


def slots(*items: tuple[str, str]) -> tuple[ScheduleEntry, ...]:
    """Convert readable HH:MM schedule entries to validated time tuples."""
    result: list[ScheduleEntry] = []
    previous_minutes = -1
    for start, title in items:
        hour, minute = (int(part) for part in start.split(":"))
        total_minutes = hour * 60 + minute
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError(f"Invalid custom schedule time: {start}")
        if total_minutes <= previous_minutes:
            raise ValueError(f"Custom schedule is not ordered at {start}: {title}")
        if not title.strip():
            raise ValueError(f"Custom schedule has an empty title at {start}")
        result.append((hour, minute, title))
        previous_minutes = total_minutes
    return tuple(result)


def weekly_schedule(
    weekday: tuple[ScheduleEntry, ...],
    saturday: tuple[ScheduleEntry, ...],
    sunday: tuple[ScheduleEntry, ...],
    overrides: dict[int, tuple[ScheduleEntry, ...]] | None = None,
) -> dict[int, tuple[ScheduleEntry, ...]]:
    schedule = {day: weekday for day in range(5)}
    schedule[5] = saturday
    schedule[6] = sunday
    schedule.update(overrides or {})
    return schedule


DZMM_WEEKDAY = slots(
    ("04:00", "Radyo Patrol Balita Alas-Kwatro"),
    ("05:00", "Pasada Balita"),
    ("06:00", "Gising Pilipinas"),
    ("07:00", "Radyo Patrol Balita Alas-Siyete"),
    ("07:30", "Gising Pilipinas"),
    ("08:00", "Tandem ng Bayan"),
    ("09:00", "Balitapatan"),
    ("10:00", "Kabayan"),
    ("11:00", "Nagseserbisyo, Nina Corpuz"),
    ("12:00", "Headline Ngayon"),
    ("12:30", "Maalaala Mo Kaya sa DZMM"),
    ("13:00", "Hello Attorney"),
    ("14:00", "Aksyon Ngayon"),
    ("15:00", "Ako 'To, si Tyang Amy!"),
    ("16:00", "Headline sa Hapon"),
    ("16:30", "ATM: Ano'ng Take Mo?"),
    ("17:30", "Isyu Spotted"),
    ("18:30", "TV Patrol sa DZMM"),
    ("20:00", "Spot Report"),
    ("21:00", "Alam Na Dis!"),
    ("22:00", "Love Konek"),
)
DZMM_SATURDAY = slots(
    ("00:00", "Remember Your Music"),
    ("04:00", "'Yan Tayo"),
    ("06:00", "Ano'ng Ganap?"),
    ("07:00", "Radyo Patrol Balita Alas-Siyete Weekend"),
    ("07:30", "Ano'ng Ganap?"),
    ("08:00", "Balita AnteMano"),
    ("09:00", "Mutya ng Masa"),
    ("10:00", "Win Today"),
    ("11:00", "Wais Konsyumer"),
    ("12:00", "Ligtas Dapat"),
    ("13:30", "MariTres"),
    ("15:00", "TrendJING"),
    ("16:00", "Tara, Game! sa DZMM"),
    ("17:00", "Pasado Serbisyo"),
    ("17:45", "TV Patrol Weekend sa DZMM"),
    ("18:45", "Kaagapay sa Kalusugan"),
    ("19:45", "SOCO sa DZMM"),
    ("20:30", "Feel Kita"),
    ("22:00", "K-Paps Playlist"),
)
DZMM_SUNDAY = slots(
    ("00:00", "Private Talks"),
    ("04:00", "The Secret of Health"),
    ("04:30", "Sunny Side Up"),
    ("06:00", "Ano'ng Ganap?"),
    ("07:00", "Radyo Patrol Balita Alas-Siyete Weekend"),
    ("07:30", "Ano'ng Ganap?"),
    ("08:00", "Dekalibreng Balita"),
    ("09:30", "Panalong Diskarte"),
    ("11:00", "Iwas Sakit, Iwas Gastos"),
    ("12:00", "Bongga Ka Jhai!"),
    ("13:30", "Konek Ka D'yan!"),
    ("15:00", "Travel ni Ahwel"),
    ("16:30", "TV Patrol Weekend sa DZMM"),
    ("17:30", "Buhay at Kalusugan"),
    ("18:30", "Story Outlook"),
    ("20:00", "K-Paps Playlist"),
    ("22:00", "Rosary Hour"),
)

UNTV_MONDAY = slots(
    ("04:00", "UNTV Community Prayer"),
    ("05:00", "Hataw Balita Ngayon"),
    ("06:30", "Good Morning Kuya"),
    ("09:00", "Itanong Mo Kay Soriano"),
    ("11:30", "UNTV C-News"),
    ("12:30", "UNTV Community Prayer"),
    ("12:35", "Sumbong Nyo, Aksyon Agad"),
    ("14:00", "Itanong Mo Kay Soriano"),
    ("16:00", "Serbisyong Bayanihan"),
    ("17:30", "Ito ang Balita"),
    ("19:00", "Itanong Mo Kay Soriano"),
    ("20:00", "UNTV Community Prayer"),
    ("20:05", "Itanong Mo Kay Soriano"),
    ("21:20", "MCGI Global Prayer for Humanity"),
    ("21:30", "Itanong Mo Kay Soriano"),
)
UNTV_TUESDAY_FRIDAY = slots(
    ("00:00", "Itanong Mo Kay Soriano"),
    ("04:00", "UNTV Community Prayer"),
    ("05:00", "Hataw Balita Ngayon"),
    ("06:30", "Good Morning Kuya"),
    ("09:00", "Itanong Mo Kay Soriano"),
    ("11:30", "UNTV C-News"),
    ("12:30", "UNTV Community Prayer"),
    ("12:35", "Sumbong Nyo, Aksyon Agad"),
    ("14:00", "Itanong Mo Kay Soriano"),
    ("16:00", "Serbisyong Bayanihan"),
    ("17:30", "Ito ang Balita"),
    ("19:00", "Itanong Mo Kay Soriano"),
    ("20:00", "Itanong Mo Kay Soriano"),
    ("21:20", "MCGI Global Prayer for Humanity"),
    ("21:30", "Itanong Mo Kay Soriano"),
)
UNTV_THURSDAY = tuple(
    (hour, minute, "Itanong Mo Kay Soriano (Huntahang Ligal)")
    if (hour, minute) == (19, 0)
    else (hour, minute, title)
    for hour, minute, title in UNTV_TUESDAY_FRIDAY
)
UNTV_SATURDAY = slots(
    ("00:00", "Itanong Mo Kay Soriano"),
    ("08:30", "MCGI Cares"),
    ("09:00", "Itanong Mo Kay Soriano"),
    ("12:00", "UNTV Community Prayer"),
    ("12:05", "UNTV Ito ang Balita Weekend"),
    ("13:00", "Itanong Mo Kay Soriano"),
    ("18:00", "How Authentic, The Bible is..."),
    ("18:15", "Itanong Mo Kay Soriano"),
    ("19:00", "Pulis @ Ur Serbis"),
    ("20:00", "Ang Inyong Kawal"),
    ("21:00", "Itanong Mo Kay Soriano"),
    ("21:15", "UNTV Community Prayer"),
    ("21:20", "Itanong Mo Kay Soriano"),
)
UNTV_SUNDAY = slots(
    ("04:55", "UNTV Community Prayer"),
    ("05:00", "Itanong Mo Kay Soriano"),
    ("06:00", "Itanong Mo Kay Soriano"),
    ("07:30", "Ang Dating Daan Mandarin Edition"),
    ("08:00", "UNTV Community Prayer"),
    ("08:05", "Itanong Mo Kay Soriano"),
    ("08:30", "Manibela"),
    ("09:00", "Doctors on TV"),
    ("10:00", "Lifesaver"),
    ("10:30", "MCGI Cares"),
    ("11:00", "The KNC Show"),
    ("11:30", "Itanong Mo Kay Soriano"),
    ("13:05", "UNTV Cup"),
    ("15:00", "Itanong Mo Kay Soriano"),
    ("16:00", "UNTV Community Prayer"),
    ("16:05", "Itanong Mo Kay Soriano"),
    ("18:00", "UNTV Community Prayer"),
    ("18:05", "Itanong Mo Kay Soriano"),
    ("20:00", "Itanong Mo Kay Soriano (pay TV) / Sign Off (free TV)"),
    ("23:15", "Itanong Mo Kay Soriano"),
)

DZRH_WEEKDAY = slots(
    ("00:00", "The Better News"),
    ("00:30", "DZRH Trending 'N Viral Show"),
    ("01:00", "NHK World-Japan"),
    ("03:00", "Balitang Promdi"),
    ("04:00", "Magandang Umaga, Pilipinas"),
    ("06:00", "Dos Por Dos"),
    ("08:00", "Damdamin Bayan"),
    ("10:00", "Operation Tulong"),
    ("11:00", "Magandang Umaga, Pilipinas (second hour replay)"),
    ("12:00", "MBC TV Network News"),
    ("13:00", "The Better News"),
    ("13:30", "DZRH Trending 'N Viral Show"),
    ("14:00", "Rapido Hataw Balita"),
    ("15:00", "Public Service Hour"),
    ("16:00", "Breaktime"),
    ("17:00", "Balansyado"),
    ("18:30", "Usapang Legal"),
    ("19:30", "Lunas"),
    ("20:30", "Lunas Extension"),
    ("21:00", "TNT: Tomorrow's News Tonight"),
    ("22:00", "Showbiz Talk Ganern"),
    ("23:00", "MBC TV Network News (replay)"),
)
DZRH_THURSDAY = slots(
    *((f"{hour:02d}:{minute:02d}", title) for hour, minute, title in DZRH_WEEKDAY if (hour, minute) < (22, 0)),
    ("22:00", "Aksyon Kababaihan"),
    ("22:30", "Showbiz Talk Ganern"),
    ("23:00", "MBC TV Network News (replay)"),
)
DZRH_SATURDAY = slots(
    ("00:00", "NHK World-Japan"),
    ("02:00", "Tita EMS Magazine"),
    ("04:00", "RH Balita"),
    ("05:00", "Tambayan"),
    ("06:00", "Adbokasiya"),
    ("07:00", "SOS: Special On Saturday"),
    ("09:00", "Executive Session"),
    ("10:30", "KKK: Kaalaman at Kabuhayan"),
    ("11:30", "Hoy Bawal Yan!"),
    ("12:00", "Scene Zone"),
    ("12:30", "Match Point"),
    ("13:00", "Dear Ate Raquel"),
    ("14:00", "Diskarte"),
    ("15:00", "Agri Asenso"),
    ("16:00", "Kaya Mo Yan!"),
    ("17:00", "Kanya-Kanyang Problema"),
    ("18:00", "Spotlight"),
    ("19:00", "Hanap Buhay Diaries"),
    ("19:30", "Lunas"),
    ("20:30", "Lunas Extension"),
    ("21:00", "Sapol Sabado"),
    ("22:00", "Gabi ng Misteryo"),
    ("23:00", "Gabi ng Bading"),
)
DZRH_SUNDAY = slots(
    ("00:00", "NHK World-Japan"),
    ("04:00", "Sunday Updates"),
    ("06:00", "Mega Balita Linggo"),
    ("07:00", "Maynila, Ito ang Pilipinas"),
    ("08:00", "Isyung Pambayan"),
    ("09:00", "DZRH Stories: Pinoy Documentaries"),
    ("10:00", "Galing sa Puso"),
    ("11:00", "Ang Galing Mo Doc"),
    ("12:00", "Sa Likod ng Kontrobersya"),
    ("13:00", "Health Check Plus"),
    ("14:00", "Misa sa Veritas"),
    ("15:00", "Experts' Opinion"),
    ("15:30", "Art 2 Art"),
    ("16:00", "Radyo Henyo"),
    ("17:00", "May Trabaho"),
    ("18:00", "Health Check Plus"),
    ("19:00", "Lunas"),
    ("19:30", "Kapanalig sa DZRH"),
    ("20:30", "The Secret of Health"),
    ("21:00", "Showbiz Talk"),
    ("22:00", "Bisaya Time"),
    ("23:00", "For Tonight Only"),
)

SMNI_MONDAY = slots(
    ("00:00", "SMNI Programs (replay)"),
    ("04:00", "Powerline"),
    ("05:00", "Balita ng Balita (replay)"),
    ("06:00", "SMNI Special Report"),
    ("07:00", "Pulso ng Bayan"),
    ("09:00", "Problema N'yo, Itawag kay Panelo"),
    ("10:00", "Laban Kasama ang Bayan"),
    ("12:00", "Makitang Muli (replay)"),
    ("13:00", "Balita ng Bansa"),
    ("14:00", "Sounds of Worship"),
    ("18:00", "SMNI Newsblast"),
    ("20:00", "Makitang Muli"),
    ("21:00", "SMNI Newsline News"),
    ("22:30", "Newsline World"),
)
SMNI_TUESDAY_THURSDAY = slots(
    ("00:00", "Makitang Muli (replay)"),
    ("01:00", "SMNI Programs (replay)"),
    *((f"{hour:02d}:{minute:02d}", title) for hour, minute, title in SMNI_MONDAY if hour >= 4),
)
SMNI_FRIDAY = slots(
    *((f"{hour:02d}:{minute:02d}", title) for hour, minute, title in SMNI_TUESDAY_THURSDAY if (hour, minute) < (16, 0)),
    ("16:00", "SMNI EntrePinoy Revolution"),
    *((f"{hour:02d}:{minute:02d}", title) for hour, minute, title in SMNI_TUESDAY_THURSDAY if (hour, minute) >= (18, 0)),
)
SMNI_SATURDAY = slots(
    ("00:00", "Makitang Muli (replay)"),
    ("01:00", "SMNI Programs (replay)"),
    ("04:00", "Powerline"),
    ("06:30", "Pinoy Legal Minds"),
    ("07:30", "Dito sa Bayan ni Juan"),
    ("09:30", "Doktor ng Bayan"),
    ("10:30", "Kingdom Force"),
    ("11:30", "SMNI Special Report"),
    ("13:00", "Kabayan Abroad"),
    ("14:00", "SMNI Feature"),
    ("18:00", "SMNI Special Report"),
    ("19:00", "Business and Politics"),
    ("20:00", "Statecraft"),
    ("21:00", "Weekender World"),
    ("23:00", "Newsline World"),
)
SMNI_SUNDAY = slots(
    ("00:00", "SMNI Programs (replay)"),
    ("11:00", "Business and Politics (replay)"),
    ("12:00", "Statecraft (replay)"),
    ("13:00", "Weekender World (replay)"),
    ("15:00", "Sounds of Worship"),
    ("18:00", "Batang Kaharian"),
    ("19:00", "SMNI Programs (replay)"),
)

CINEMO_PH_WEEKDAY = slots(
    ("01:00", "Cine Silip"),
    ("03:00", "Cine Serye Pre: Mars Ravelo's Lastikman"),
    ("04:00", "Cine Serye Pre: Galema: Anak ni Zuma"),
    ("05:00", "Super Morning Sine"),
    ("07:00", "Cine Takilya"),
    ("09:00", "Cine Komedya"),
    ("11:00", "Cine Saya"),
    ("13:00", "Cine Astig"),
    ("15:00", "Cine Kamao"),
    ("17:00", "Cine Tawanan"),
    ("19:00", "Cine Barako"),
    ("21:00", "Cine Aksyon"),
    ("23:00", "Cine Gigil"),
)
CINEMO_PH_SATURDAY = slots(
    ("01:00", "Cine Silip"),
    ("03:00", "Super Morning Sine"),
    ("05:00", "Cine Una"),
    ("07:00", "Cine Sigaw"),
    ("09:00", "Cine Kilig"),
    ("11:00", "Cine Saya"),
    ("13:00", "Cine Matapang"),
    ("15:00", "Weekend Movie Bonding"),
    ("17:00", "CineMo Box Office"),
    ("19:00", "Dolphy Hari ng Komedya"),
    ("21:00", "Cine Maton"),
    ("23:00", "Cine Patok"),
)
CINEMO_PH_SUNDAY = slots(
    ("01:00", "Cine Silip"),
    ("03:00", "Super Morning Sine"),
    ("05:00", "Cine Una"),
    ("07:00", "Cine Dekalibre"),
    ("09:00", "Cine Kilig"),
    ("11:00", "Cine Saya"),
    ("13:00", "Ang Alamat ni Agimat"),
    ("15:00", "Weekend Movie Bonding"),
    ("17:00", "CineMo Box Office"),
    ("19:00", "Markang Daboy"),
    ("21:00", "Cine Matapang"),
    ("23:00", "Cine Patok"),
)

CINEMO_GLOBAL_WEEKDAY = slots(
    ("00:00", "Cinekwela"),
    ("01:00", "Cinesaya"),
    ("03:00", "Cineserye"),
    ("04:00", "Super Sine"),
    ("06:00", "Cinetakilya"),
    ("08:00", "Cinekomedya"),
    ("10:00", "Cinesaya"),
    ("12:00", "Cineastig"),
    ("14:00", "Cinekamao"),
    ("16:00", "Cinetawanan"),
    ("18:00", "Cinebarako"),
    ("20:00", "Cineserye"),
    ("21:00", "Cineaksyon"),
    ("23:00", "Cinekwela"),
)
CINEMO_GLOBAL_SATURDAY = slots(
    ("00:00", "Cinekwela"),
    ("01:00", "Cinesaya"),
    ("03:00", "Super Sine"),
    ("05:00", "Cineuna"),
    ("07:00", "Cinesigaw"),
    ("09:00", "Cinekilig"),
    ("11:00", "Cinesaya"),
    ("13:00", "Cinematapang"),
    ("15:00", "Cinesiga"),
    ("17:00", "Super Sabado Sine"),
    ("19:00", "Dolphy Hari Ng Comedy"),
    ("21:00", "Cinematon"),
    ("23:00", "Cinekwela"),
)
CINEMO_GLOBAL_SUNDAY = slots(
    ("00:00", "Cinekwela"),
    ("01:00", "Cinesaya"),
    ("03:00", "Super Sine"),
    ("05:00", "Cineuna"),
    ("07:00", "Cinesigaw"),
    ("09:00", "Cinekilig"),
    ("11:00", "Cinesaya"),
    ("13:00", "Alamat Ni Agimat"),
    ("15:00", "Cinesiga"),
    ("17:00", "Cinemo Box Office"),
    ("19:00", "Markang Daboy"),
    ("21:00", "Cinematon"),
    ("23:00", "Cinekwela"),
)

CUSTOM_CHANNELS = (
    CustomChannel(
        "DZMM.Radyo.Patrol.us2",
        ("DZMM TeleRadyo", "DZMM Teleradyo SD"),
        "https://tvradioschedules.fandom.com/wiki/"
        "DZMM_%26_DZMM_TeleRadyo_Program_Schedule_(TBA)",
        weekly_schedule(DZMM_WEEKDAY, DZMM_SATURDAY, DZMM_SUNDAY),
    ),
    CustomChannel(
        "gsat.UNTV",
        ("UNTV", "UNTV News and Rescue"),
        "https://russel.fandom.com/wiki/UNTV_Program_Schedule",
        weekly_schedule(
            UNTV_TUESDAY_FRIDAY,
            UNTV_SATURDAY,
            UNTV_SUNDAY,
            {0: UNTV_MONDAY, 3: UNTV_THURSDAY},
        ),
    ),
    CustomChannel(
        "gsat.DZRH_NEWS_TV",
        ("DZRH TV", "DZRH News Television"),
        "https://russel.fandom.com/wiki/DZRH_TV_Program_Schedule",
        weekly_schedule(
            DZRH_WEEKDAY,
            DZRH_SATURDAY,
            DZRH_SUNDAY,
            {3: DZRH_THURSDAY},
        ),
    ),
    CustomChannel(
        "gsat.SMNI",
        ("SMNI", "SMNI News Channel"),
        "https://tvradioschedules.fandom.com/wiki/SMNI_Program_Schedule",
        weekly_schedule(
            SMNI_TUESDAY_THURSDAY,
            SMNI_SATURDAY,
            SMNI_SUNDAY,
            {0: SMNI_MONDAY, 4: SMNI_FRIDAY},
        ),
    ),
    CustomChannel(
        "CineMo.ph",
        ("Cinemo PH", "CineMo!", "CINEMO!"),
        "https://philippinetelevision.fandom.com/wiki/CineMo!_Program_Schedule",
        weekly_schedule(
            CINEMO_PH_WEEKDAY,
            CINEMO_PH_SATURDAY,
            CINEMO_PH_SUNDAY,
        ),
    ),
    CustomChannel(
        "CineMoGlobal.ph",
        ("Cinemo Global", "CineMo Global"),
        "User-provided recurring schedule",
        weekly_schedule(
            CINEMO_GLOBAL_WEEKDAY,
            CINEMO_GLOBAL_SATURDAY,
            CINEMO_GLOBAL_SUNDAY,
        ),
    ),
)


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


def xmltv_timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%d%H%M%S %z")


def generate_custom_guides(
    target_ids: set[str], now: datetime | None = None
) -> tuple[
    dict[str, ET.Element],
    dict[str, list[ET.Element]],
    dict[str, str],
]:
    """Generate rolling XMLTV entries from the manually maintained schedules."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(MANILA_TIMEZONE)
    first_date = local_now.date() - timedelta(days=CUSTOM_LOOKBACK_DAYS)
    last_date = local_now.date() + timedelta(days=CUSTOM_LOOKAHEAD_DAYS)
    window_start = datetime.combine(first_date, datetime.min.time(), MANILA_TIMEZONE)
    window_end = datetime.combine(
        last_date + timedelta(days=1), datetime.min.time(), MANILA_TIMEZONE
    )

    channels: dict[str, ET.Element] = {}
    programmes: dict[str, list[ET.Element]] = {}
    source_urls: dict[str, str] = {}

    for custom in CUSTOM_CHANNELS:
        if custom.channel_id not in target_ids:
            continue
        if set(custom.schedule_by_weekday) != set(range(7)):
            raise ValueError(
                f"Custom schedule for {custom.channel_id} does not cover all weekdays"
            )

        events: list[tuple[datetime, str]] = []
        day = first_date - timedelta(days=1)
        final_generation_date = last_date + timedelta(days=1)
        while day <= final_generation_date:
            for hour, minute, title in custom.schedule_by_weekday[day.weekday()]:
                events.append(
                    (
                        datetime(
                            day.year,
                            day.month,
                            day.day,
                            hour,
                            minute,
                            tzinfo=MANILA_TIMEZONE,
                        ),
                        title,
                    )
                )
            day += timedelta(days=1)
        events.sort(key=lambda item: item[0])

        entries: list[ET.Element] = []
        for (start, title), (stop, _) in zip(events, events[1:]):
            if stop <= window_start or start >= window_end:
                continue
            if stop <= start:
                raise ValueError(
                    f"Custom schedule for {custom.channel_id} has a non-positive slot"
                )
            programme = ET.Element(
                "programme",
                {
                    "start": xmltv_timestamp(start),
                    "stop": xmltv_timestamp(stop),
                    "channel": custom.channel_id,
                },
            )
            ET.SubElement(programme, "title", {"lang": "en"}).text = title
            entries.append(programme)

        if not entries:
            raise ValueError(f"Custom schedule for {custom.channel_id} generated no data")

        channel = ET.Element("channel", {"id": custom.channel_id})
        for display_name in custom.display_names:
            ET.SubElement(channel, "display-name", {"lang": "en"}).text = display_name
        channels[custom.channel_id] = channel
        programmes[custom.channel_id] = entries
        source_urls[custom.channel_id] = custom.source_url

    return channels, programmes, source_urls


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
    selected_channels, selected_programmes, custom_source_urls = (
        generate_custom_guides(target_ids)
    )
    selected_sources = {
        channel_id: "custom recurring schedule"
        for channel_id in selected_programmes
    }
    failed_sources: list[str] = []

    print(
        f"Generated recurring schedules for {len(selected_programmes)} custom channel(s)"
    )

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
        "custom_schedule_sources": dict(sorted(custom_source_urls.items())),
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
