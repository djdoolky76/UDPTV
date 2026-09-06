# UDPTV consolidated EPG

Use only this URL in the application:

```text
https://raw.githubusercontent.com/djdoolky76/UDPTV/main/epgs/udptv-epg.xml.gz
```

The grabber filters every provider to the IDs in `udptv-tvg-ids.txt`, chooses
one provider per channel, adds the local recurring schedules below, and
publishes both XML and XML.GZ. The generated `epgs/udptv-epg-report.json` shows
the winning provider for every channel and lists IDs that had no current
programmes.

The GitHub Actions workflow refreshes this single guide every 12 hours. Custom
schedules are regenerated in Philippine time with one day of lookback and 14
days ahead, so their XMLTV dates keep moving forward automatically.

## Recommended mappings for blank channels

Set these `tvg_id` values in the content library. Two channel entries may share
an ID when they carry the same schedule.

| Channel | Set `tvg_id` to |
| --- | --- |
| Aniplus | `ANIPLUS.HD.sg` |
| Cinema One PH | `cinemaone.ph` |
| Cinemo Global | `cinemo.global` |
| Cinemo PH | `cinemo.ph` |
| CLTV36 | `cltv36.ph` |
| DZMM Teleradyo | `dzmm.teleradyo.ph` |
| DZRH News TV | `dzrhnewstv.ph` |
| Heart of Asia | `heartofasia.ph` |
| Metro Channel | `metrochannel.ph` |
| SNMI | `snmi.ph` |
| Tap Action Flix | `TAPACTIONFLIX.ph` |
| UNTV | `untv.ph` |
| AMC | `AMC.HD.us2` |
| BBC Food | `Amazon.US.BBCFood` |
| FOX11 | `KTTV-DT.us_locals1` |
| RCN Novelas | `RCN.Novelas.co` |
| TVBS | `TVBS.Asia.sg` |
| Virgin Media One | `Virgin.Media.One.HD.ie` |
| Virgin Media Two | `Virgin.Media.Two.HD.ie` |
| Virgin Media Three | `Virgin.Media.Three.HD.ie` |
| Virgin Media Four | `Virgin.Media.Four.HD.ie` |
| NBC Golf Channel CA | `Golf.Channel.HD.ca2` |

The exported Buko ID had a trailing space. Change `buko ` to `buko`. Its
current providers declare the channel but do not currently publish programmes.

## Custom recurring schedules

These IDs are generated before internet XMLTV providers are checked, so the
custom timetable is authoritative for them:

| Channel | XMLTV ID | Schedule source |
| --- | --- | --- |
| DZMM TeleRadyo | `dzmm.teleradyo.ph` | [DZMM schedule](https://tvradioschedules.fandom.com/wiki/DZMM_%26_DZMM_TeleRadyo_Program_Schedule_(TBA)) |
| UNTV | `untv.ph` | [UNTV schedule](https://russel.fandom.com/wiki/UNTV_Program_Schedule) |
| DZRH News TV | `dzrhnewstv.ph` | [DZRH TV schedule](https://russel.fandom.com/wiki/DZRH_TV_Program_Schedule) |
| SNMI | `snmi.ph` | [SMNI schedule](https://tvradioschedules.fandom.com/wiki/SMNI_Program_Schedule) |
| Cinemo PH | `cinemo.ph` | [CineMo! schedule](https://philippinetelevision.fandom.com/wiki/CineMo!_Program_Schedule) |
| Cinemo Global | `cinemo.global` | User-provided weekly schedule |
| CLTV36 | `cltv36.ph` | [CLTV36 programs](https://cltv36.tv/tv-programs/) plus current CLTV36 announcements |
| Heart of Asia | `heartofasia.ph` | [Heart of Asia schedule](https://philippinetelevision.fandom.com/wiki/Heart_of_Asia_Program_Schedule) |

The recurring programme pages are references, not live XMLTV feeds. When a
broadcaster changes its lineup, update the matching schedule constants in
`udptv-epg-grabber.py`. CLTV36 uses `CLTV36 Programming` during hours for which
the broadcaster has not published an exact programme.

Heart of Asia follows distinct Monday–Thursday, Friday, Saturday, and Sunday
lineups. Movie slots without film titles retain their published block names.
Its source gives no overnight listings: midnight–06:00 is labelled
`Schedule not provided`, and late-evening entries are bounded at midnight. This does not
assert that the channel is off air. The lineup is manually maintained; each
scheduled run automatically advances the programme dates, not the show titles.

## Dynamic local schedule

Metro Channel uses `metrochannel.ph`. The grabber downloads all dated listings
available from [On TV Tonight](https://www.ontvtonight.com/guide/listings/channel/1473142439/metro-channel-philippines.html)
on every run and combines their overlapping boundaries. The former weekly
schedule remains only as a fallback for a temporary website outage.

Cinema One PH uses `cinemaone.ph`. The consolidator rewrites the existing
`cinema-one.click` provider ID and supplements missing start times from the
[ClickTheCity Cinema One schedule](https://www.clickthecity.com/tv/channels/cinema-one)
on every run.

## Targeted provider feeds

### Mediaquest Cignal

The [Mediaquest Cignal feed](https://github.com/djdoolky76/Mediaquest-EPG/raw/refs/heads/main/cignal_epg.xml.gz)
was resynchronized on 2026-09-06. All **60 declared channel IDs** are included,
and every one had programmes during validation. The feed is bound to an explicit
allowlist in the grabber so later API changes must be reviewed before they can
silently alter the public UDPTV lineup.

The refresh added 34 IDs:

```text
abc_australia, amagi, arirang_sd, bbcworld_news_sd, bloomberg_sd, cg_a2z,
cg_abante_news, cg_animax_sd_new, cg_axn_sd, cg_bbclifestyle, cg_hitsnow,
cg_moonbug_kids_sd, cg_ncaa, cg_ps_hd1, cg_tvnmovie, cgtn, cgtn-test,
channelnewsasia, depedch_sd, dr_aljazeera, dr_cctv4, dr_lifetime,
dr_nickelodeon, dr_rockextreme, fashiontvhd, fifafast, globaltrekker,
hits_hd1, hits_movies, ibc13_sd_new, kapatid_hd, pl_sdi10, tv5, tvmaria_prd
```

Seven retired Mediaquest-only IDs were removed from the UDPTV target list because
the current source no longer declares them and no other provider produced current
programmes for them: `cartoonnetworkhd`, `celmovie_pinoy_sd`, `cg_tagalogmovie`,
`cg_thrill_sd`, `cg_warnerhd`, `kbsworld`, and `kix_hd1`.

### Selected JioTV feed

The private [JioTV XMLTV deployment](https://jioepg.djdoolky76.com/epg.xml.gz)
contains more than 1,000 channels. The consolidator streams the feed but retains
only the following 13 channels. Their `.jio` IDs are deliberately separate from
existing UDPTV mappings, so both versions can coexist.

| JioTV channel | Jio source ID | UDPTV XMLTV ID |
| --- | --- | --- |
| Mirror Now | `jiotv.491` | `mirrornow.jio` |
| Movies Now HD | `jiotv.151` | `moviesnow.jio` |
| MNX HD | `jiotv.877` | `mnx.jio` |
| MN+ HD | `jiotv.477` | `mnplus.jio` |
| Romedy Now | `jiotv.1401` | `romedynow.jio` |
| Star Gold HD | `jiotv.156` | `stargold.jio` |
| Star Gold 2 HD | `jiotv.3096` | `stargold2.jio` |
| Star Gold Romance | `jiotv.3097` | `stargoldromance.jio` |
| Star Gold Select HD | `jiotv.1113` | `stargoldselect.jio` |
| Star Gold Thrills | `jiotv.3098` | `stargoldthrills.jio` |
| Star Movies HD | `jiotv.1104` | `starmovies.jio` |
| Star Movies Select HD | `jiotv.1110` | `starmoviesselect.jio` |
| Sony Pix HD | `jiotv.762` | `sonypixhd.jio` |

The upstream display names and programme metadata are preserved; only channel
references are rewritten. If this source is temporarily unavailable, still-current
entries from the previous consolidated output may be retained by the existing
outage fallback. No other Jio channel is written to the UDPTV guide.

### EPGShare Latvia Go3 Sports

The [EPGShare Latvia LV1 XMLTV feed](https://epgshare01.online/epgshare01/epg_ripper_LV1.xml.gz)
is restricted to the four IDs below. The provider's
[TXT index](https://epgshare01.online/epgshare01/epg_ripper_LV1.txt) is used for
ID verification only.

- `Go3.Sport.1.HD.lv`
- `Go3.Sport.2.HD.lv`
- `Go3.Sport.3.HD.lv`
- `Go3.Sport.Open.HD.lv`

## No trustworthy current XMLTV mapping

These were deliberately not assigned an unrelated schedule:

- Aliw TV
- MYX PH
- Arena Sport Premium 1–5
- WNBA Event 1–3
- Abu Dhabi Sports 1–2

Some providers declare MYX PH and Abu Dhabi Sports but currently return zero
programme entries. They should only be mapped after their feeds begin
publishing real schedules.
