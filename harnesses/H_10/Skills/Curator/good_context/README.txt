Good_context: human judgements of nine finished builds, cleaned up, to be given to the agents
as examples of what a person notices, how they assign blame, and what fix they ask for.

One file per subject (same layout as human/: defects, blame, fix, other) and general_rules.txt
with what they have in common. 03_monstera_pot, 04_skull (2026-09-11) and 06_tablecloth_drape
(2026-09-12) are judgements of this harness's own runs: the first says a build the checker gave
12 defects was 90% right; the second says why the head was a box and how the hand build fixed it
(plate_loft); the third says the legs were typed instead of read from the photo, and how the hand
build (run_003, tool outline_trace) traced them — the "was the reference measured?" question of
human-judgement rule 9. The wording is the human's; a few gaps were filled from the human's own
blame so every defect has a class and a fix.

How to use it without cheating: when the checker or the blame agent is judging one of these nine
subjects, give it only the OTHER eight files plus general_rules.txt. The file for the subject
itself is the answer key and stays out of the prompt. For new tasks, all nine can go in.
Since 2026-09-12 the driver does this itself: run_v2 calls harness.hide_answer_keys(view, task)
after syncing a worker's view, which deletes from that view every file here whose name shares a
subject word with the task (08_shark -> 17_shark.txt, 09_thors_hammer -> both hammer files,
10_low_poly_dog -> 20_low_poly_dog.txt, 07_sneaker -> 14_sneaker.txt, ...). The next sync
restores it. Nothing in the store changes.
