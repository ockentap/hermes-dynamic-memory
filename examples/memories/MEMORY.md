# Dynamic Memory Index — keyword,keyword,keyword → file.md
# One line per topic file. This file IS the index: it is injected verbatim
# into the system prompt at session start. Topic files stay on disk and are
# read only when a line routes to them.
#
# Routing: score each line's whole keyword SET against the conversation, and
# prefer the line that fits best overall — not the first line sharing a word.
# Follow obviously related terms that are not spelled out in a line.
#
# Qualifier prefixes (user-assigned only):
#   !! critical — never edit without explicit user approval
#   !  pinned   — never prune
smart,home,zigbee,mqtt,homeassistant,light,bulb,scene,automations → smart-home.md
camera,photography,dslr,lens,aperture,exposure,tripod,raw,editing → camera-gear.md
travel,visa,schengen,flight,hotel,itinerary,passport,border,customs → travel-planning.md
cooking,recipes,bread,sourdough,fermentation,kitchen,starter,baking → cooking-notes.md
finances,budget,taxes,deductions,filing,deadline,invoice,vat → money-admin.md
golf,clubs,swing,handicap,course,putting,driver,iron → golf-notes.md
car,maintenance,transmission,oil,tires,garage,service,brakes → car-log.md
running,training,marathon,pace,shoes,injury,recovery,plan → running-log.md
