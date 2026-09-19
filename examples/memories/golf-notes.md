# Golf Notes

## Handicap and goals
Index trending from 14.2 toward 12 by season end. Priority: putting inside
6 feet; lag putting is fine.

## Clubs
- Driver: 9°, stock stiff shaft, set to +1° loft after a launch-monitor session.
- Irons: standard loft, +1/2" length, mid-size grips.
- Wedge gapping re-checked twice a season: 50/56/62.

## Lessons that stuck
- "Club up into the wind, swing smooth" — fixed the ballooned long irons.
- The transmission repair in spring 2026 came out of the golf fund; the new
  putter waits until next year. Cross-referenced in `car-log.md`.

## How this file is routed to
This is the golf+**clubs** file. The car file owns golf+**car** — its index
line carries the transmission and service keywords, so a conversation about
a golf cart never routes here even though this line also contains `golf` in
prose context. Set-level matching is what keeps the two apart; a per-keyword
scorer would rank both lines equally.
