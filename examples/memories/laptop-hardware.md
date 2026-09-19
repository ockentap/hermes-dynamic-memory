# Laptop Hardware

## Firmware
- Check the vendor's release notes before updating; firmware updates are the
  one category of change where "it worked yesterday" is not evidence.
- Battery charge thresholds, if the vendor supports them, meaningfully extend
  pack life for a machine that lives on a desk.

## Thermal
- Sustained performance is set by cooling, not by the spec sheet. Two identical
  CPUs in different chassis perform differently under a long compile.
- If the fans spin up under light load, that is dust or a bad thermal
  interface, not a new normal.

## Peripherals
- Docking stations with their own firmware are a second computer that can
  break independently. When the display doesn't wake, suspect the dock first.

## How this file is routed to
Keywords: `laptop`, `thinkpad`, `firmware`, `battery`, `thermal`, `fankey`,
`bios`. `firmware` also appears in `home-network.md`, and that is intentional
— the two lines are separated by everything else in their sets. A question
about a router's firmware scores the network line densely; a question about
fan noise and charge thresholds does not.
