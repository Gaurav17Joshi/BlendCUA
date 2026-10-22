---
name: structural-ownership-before-presentation
description: Read this when a final presentation or cleanup step will review a multi-part model assembled in earlier geometry steps.
evidence: 09_skull_run_001 step_006
---

# Finish structural connections before presentation

A presentation step may expose a floating part, detached hinge, missing root, or
crudely capped opening, but it is the wrong place to first build that structure.
The geometry step that creates a part must also own its attachment, seating, and
close/side-view proof; the handover should leave lighting and cleanup with no new
topology risk. A late support bar or replacement cup can preserve a bbox while
still failing the anatomy that the earlier step should have established.

Before planning the final still, list every relationship the review will call
structural—teeth seated in an alveolar corridor, ramus joined to the jaw body,
rim/wall/back ordering—and assign its build and measurement to the owning step.
The final step can rerender and report those invariants, not postpone them.
