"""Station identity and station selection.

The trip files have no station id, only a name and coordinates, and names drift between years
(case, accents, spacing, and real renames such as "Beaubien / 8e avenue" becoming
"Parc Beaubien (Beaubien / 8e avenue)"). We therefore identify a station by *location*: each
historical name is linked to the nearest station in the live GBFS feed, which carries a stable
``station_id`` and a dock ``capacity``.
"""
