---
name: world-background-nodes
description: Read this before trusting a world-colour helper on a custom node tree.
evidence: 05_wine_glass_run_001 step_003
---

# World background nodes

A world colour helper that looks up a node by the literal name `Background` is
not proof that the rendered world changed: custom node trees may rename one or
more connected `BACKGROUND` nodes. When the world is custom, inspect and set
every actual `BACKGROUND` node, then audit its colour and strength; do not infer
the live environment from the helper call or from a stale validation JSON.

The wine-glass run discovered this only after repeated presentation audits: the
connected nodes were named `Accepted Ambient Background` and `Neutral Camera
Background`, so the named lookup silently left the world at its old values.
