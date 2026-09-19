# Smart Home

## Devices
- Hub: local-only, no cloud dependency for automations.
- Lights: Zigbee bulbs in the living room and office, dumb switches everywhere
  else (guests should not need an app to turn on a light).
- Sensors: door contact on the front entrance, temperature in the hallway.

## Automations
- Sunset → living room scenes on, brightness 40%.
- Motion after 23:00 → hallway light at 10%, one-minute timeout.
- Everything off when the last phone leaves the network.

## Standing notes
- Keep automations idempotent; a scene triggered twice should be a no-op.
- Anything that needs an internet round-trip to turn on a light is a design
  failure.
