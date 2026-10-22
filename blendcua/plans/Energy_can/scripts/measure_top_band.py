from pathlib import Path
import sys
import numpy as np
from PIL import Image
for s in (sys.stdout,sys.stderr):
    try:s.reconfigure(encoding='utf-8',errors='replace')
    except Exception:pass
ROOT=Path(__file__).resolve().parents[1]
a=np.asarray(Image.open(ROOT/'reference.png').convert('RGB')).astype(float)
g=a.mean(2); sat=a.max(2)-a.min(2)
# Interior-only top-collar crop; report every threshold's contiguous active rows.
for t in [140,160,180,200]:
    m=(g>t)&(sat<105)
    counts=m[:,300:731].sum(1)
    active=(counts>=5); ys=np.where(active & (np.arange(len(active))>=125) & (np.arange(len(active))<=205))[0]
    runs=[]
    if len(ys):
        s=p=int(ys[0])
        for y in ys[1:]:
            y=int(y)
            if y-p>3: runs.append((s,p,int(counts[s:p+1].max()),int(counts[s:p+1].sum())));s=y
            p=y
        runs.append((s,p,int(counts[s:p+1].max()),int(counts[s:p+1].sum())))
    print('threshold',t,'top-collar runs',runs)
print('PASS top collar band diagnostic')
