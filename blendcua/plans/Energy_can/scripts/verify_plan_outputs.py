from pathlib import Path
import json, re, sys
from PIL import Image

root=Path(__file__).resolve().parents[1]
plan=root/'Energy_can_plan.md'
assert plan.read_text(encoding='utf-8').splitlines()[0]=='<!-- ref-image: reference.png -->'
required=[root/'reference.png',root/'marked_Energy_can.json',root/'marked_Energy_can.jpg',root/'scripts/monster_logo_cutout.png',root/'scripts/segmentation_bounds.json',root/'scripts/reference_color_samples.json']
for p in required: assert p.exists() and p.stat().st_size>0, p
marks=json.loads((root/'marked_Energy_can.json').read_text(encoding='utf-8'))
assert isinstance(marks,list) and len(marks)==18
for m in marks:
    assert set(('name','group','u','v','px','note')).issubset(m)
    assert len(m['px'])==2 and 0<=m['u']<=1 and 0<=m['v']<=1
    assert abs(m['u']-m['px'][0]/1024)<2e-6
    assert abs(m['v']-m['px'][1]/1536)<2e-6
text=plan.read_text(encoding='utf-8')
assert text.count('**Review:**')==4
assert text.count('**Important**')==4 and text.count('**Other**')==4
for p in [root/'reference.png',root/'marked_Energy_can.jpg',root/'scripts/monster_logo_cutout.png']:
    im=Image.open(p)
    print(p.name, im.size, im.mode)
print('PASS plan header, required outputs, landmark schema, and four review blocks')
