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

The recurring programme pages are references, not live XMLTV feeds. When a
broadcaster changes its lineup, update the matching schedule constants in
`udptv-epg-grabber.py`. CLTV36 uses `CLTV36 Programming` during hours for which
the broadcaster has not published an exact programme.

## Dynamic local schedule

Metro Channel uses `metrochannel.ph`. The grabber downloads all dated listings
available from [On TV Tonight](https://www.ontvtonight.com/guide/listings/channel/1473142439/metro-channel-philippines.html)
on every run and combines their overlapping boundaries. The former weekly
schedule remains only as a fallback for a temporary website outage.

Cinema One PH uses `cinemaone.ph`. The consolidator rewrites the existing
`cinema-one.click` provider ID and supplements missing start times from the
[ClickTheCity Cinema One schedule](https://www.clickthecity.com/tv/channels/cinema-one)
on every run.

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
