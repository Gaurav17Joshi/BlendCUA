from pathlib import Path
import sys,json
import numpy as np
from PIL import Image
import cv2
for s in (sys.stdout,sys.stderr):
    try:s.reconfigure(encoding='utf-8',errors='replace')
    except Exception:pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
a=np.asarray(Image.open(ROOT/'reference.png').convert('RGB')).astype(float); h,w=a.shape[:2]; g=a.mean(2)
bg=np.zeros((h,3))
for y in range(h): bg[y]=np.median(np.concatenate([a[y,:180],a[y,850:]],0),0)
diff=np.linalg.norm(a-bg[:,None,:],axis=2)
print('row spans after local-background difference mask; largest contiguous run in x=180..850')
out=[]
for t in [8,12,20]:
    m=((diff>t)|(g<bg.mean(1)[:,None]-25)).astype('uint8')
    m[:60]=0;m[1490:]=0;m[:,:180]=0;m[:,850:]=0
    m=cv2.morphologyEx(m,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))
    print('threshold',t)
    for y in [80,85,90,92,95,100,105,110,115,120,125,130,135,140,145,150,155,160,170,180,190,200,210,220,230,240,300,600,900,1200,1350,1380,1390,1400,1410,1415,1420,1430,1440,1450,1460,1465,1470]:
        xs=np.where(m[y]>0)[0]
        # choose run closest to center and length >=3
        runs=[]
        if len(xs):
            s=p=int(xs[0])
            for x in xs[1:]:
                x=int(x)
                if x-p>4:runs.append((s,p));s=x
                p=x
            runs.append((s,p))
        runs=[r for r in runs if r[1]-r[0]+1>=3]
        if runs:
            r=min(runs,key=lambda q:abs((q[0]+q[1])/2-w/2))
            print(f' y={y:4d} x={r[0]:3d}..{r[1]:3d} width={r[1]-r[0]+1:3d} w/H?')
            if t==12: out.append({'y':y,'left':r[0],'right':r[1],'width':r[1]-r[0]+1})
        else: print(f' y={y:4d} NONE')
print('ratios for threshold-12 selected rows:')
for p in out:
    print(f" y={p['y']:4d}: diameter/imageW={p['width']/w:.6f}, diameter/full-height-1379={p['width']/1379:.6f}, v={p['y']/h:.6f}")
(OUT/'subject_row_spans.json').write_text(json.dumps({'image_size_px':[w,h],'t12_spans':out},indent=2),encoding='utf-8')
print('PASS wrote subject_row_spans.json')
