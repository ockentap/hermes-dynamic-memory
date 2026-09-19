# Home Network

## Topology
- Flat network with a single DHCP authority. A second DHCP server that someone
  forgot they enabled is the single most common cause of intermittent
  connectivity that no log explains.
- Static leases for anything addressed by IP. Dynamic addresses for everything
  addressed by name.

## DNS and names
- Local resolver with a fallback upstream. When resolution fails, the first
  question is always which resolver answered.
- `.local` name collisions with the discovery protocol cause slow lookups
  rather than failed ones, which is why they go unnoticed for months.

## Firmware
- Router firmware updates on a schedule, with the config exported first. The
  export is the rollback plan.
- Anything exposed to the internet gets patched on release, not on
  convenience.

## How this file is routed to
Keywords: `router`, `firmware`, `openwrt`, `modem`, `subnet`, `dns`, `dhcp`.
The word `firmware` is shared with `laptop-hardware.md`; the remaining six
keywords in each set are not. This is the design working as intended — a
single shared keyword is not a routing signal, and set-level scoring is what
prevents it from becoming one.
