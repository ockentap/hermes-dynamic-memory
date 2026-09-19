# Camera Gear

## Body and lenses
- Body: mirrorless, 24 MP, full frame. Two spare batteries; the grip comes off
  for travel.
- Primes: 35mm f/1.8 (walkaround), 85mm f/1.8 (portraits).
- Zoom: 24–70mm f/4, weather-sealed — the lens that actually leaves the house.

## Settings that work
- Aperture priority, auto-ISO capped at 6400, minimum shutter 1/125 in low light.
- RAW + JPEG; JPEGs only for quick sharing, RAW always archived.
- Tripod for anything slower than 1/30 — the stabilizer isn't a substitute.

## Editing
- Import, cull, then edit in that order. Never edit before culling.
- Preset baseline: slight contrast curve, highlight recovery on skies, no
  sharpening above 40.

## How this file is routed to
The index line carries `camera,photography,dslr,lens,aperture,exposure,tripod`.
The literal string `dslr` is the only entry here that appears in the line, but
a question about "upgrading my DSLR" routes here anyway — the model makes the
associative jump from a term in the conversation to the line's keyword set.
That is the model-side fuzziness the design relies on, and it is why no
embedding index is needed.
