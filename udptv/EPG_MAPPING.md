# UDPTV consolidated EPG

Use only this URL in the application:

```text
https://raw.githubusercontent.com/djdoolky76/UDPTV/main/epgs/udptv-epg.xml.gz
```

The grabber filters every provider to the IDs in `udptv-tvg-ids.txt`, chooses
one provider per channel, and publishes both XML and XML.GZ. The generated
`epgs/udptv-epg-report.json` shows the winning provider for every channel and
lists IDs that had no current programmes.

## Recommended mappings for blank channels

Set these `tvg_id` values in the content library. Two channel entries may share
an ID when they carry the same schedule.

| Channel | Set `tvg_id` to |
| --- | --- |
| Aniplus | `ANIPLUS.HD.sg` |
| DZMM Teleradyo SD | `DZMM.Radyo.Patrol.us2` |
| DZRH TV | `gsat.DZRH_NEWS_TV` |
| SMNI | `gsat.SMNI` |
| Tap Action Flix | `TAPACTIONFLIX.ph` |
| UNTV | `gsat.UNTV` |
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

## No trustworthy current XMLTV mapping

These were deliberately not assigned an unrelated schedule:

- Aliw TV
- CINEMO! (Cinemo Global and Cinemo PH)
- CLTV 36
- Metro Channel
- MYX PH
- Arena Sport Premium 1–5
- WNBA Event 1–3
- Abu Dhabi Sports 1–2

Some providers declare CINEMO!, Metro Channel, MYX PH, and Abu Dhabi Sports but
currently return zero programme entries. They should only be mapped after their
feeds begin publishing real schedules.
