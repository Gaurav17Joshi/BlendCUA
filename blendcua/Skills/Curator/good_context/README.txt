Good_context: human judgements of six finished builds, cleaned up, to be given to the agents
as examples of what a person notices, how they assign blame, and what fix they ask for.

One file per subject (same layout as human/: defects, blame, fix, other) and general_rules.txt
with what they have in common. The wording is the human's; a few gaps were filled from the
human's own blame so every defect has a class and a fix.

How to use it without cheating: when the checker or the blame agent is judging one of these six
subjects, give it only the OTHER five files plus general_rules.txt. The file for the subject
itself is the answer key and stays out of the prompt. For new tasks, all six can go in.
