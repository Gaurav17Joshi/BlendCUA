from pathlib import Path
import json, sys
import numpy as np
from PIL import Image

for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding='utf-8',errors='replace')
    except Exception: pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
a=np.asarray(Image.open(ROOT/'reference.png').convert('RGB')).astype(float)
h,w=a.shape[:2]
# Per-row side-background model, with both side strips well outside the can.
bg=np.zeros((h,3),float)
for y in range(h): bg[y]=np.median(np.concatenate([a[y,0:180],a[y,850:1024]],axis=0),axis=0)
diff=np.linalg.norm(a-bg[:,None,:],axis=2)
g=a.mean(2)
# Dark can plus progressively looser neutral-metal difference masks.
try:
 import cv2
except Exception as e:
 print('FAIL cv2 required:',e); raise
results=[]
for t in [4,6,8,10,12,16,20]:
    mask=(diff>t) | (g < bg[:,None,:].mean(2)-25)
    # limit plausible object search, close small gaps in the cap/body connection
    region=np.zeros_like(mask); region[60:1490,180:850]=True; mask &= region
    k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7))
    closed=cv2.morphologyEx(mask.astype(np.uint8),cv2.MORPH_CLOSE,k)
    n,lab,stats,cent=cv2.connectedComponentsWithStats(closed,8)
    comps=[]
    for i in range(1,n):
        area=int(stats[i,cv2.CC_STAT_AREA])
        x=int(stats[i,cv2.CC_STAT_LEFT]); y=int(stats[i,cv2.CC_STAT_TOP])
        ww=int(stats[i,cv2.CC_STAT_WIDTH]); hh=int(stats[i,cv2.CC_STAT_HEIGHT])
        if area>500: comps.append((area,(x,y,x+ww-1,y+hh-1)))
    comps.sort(reverse=True)
    results.append({'threshold':t,'components':comps[:5]})
    print(f'diff threshold {t:2d}:',comps[:5])
    if comps and t == 12:
        x0, y0, x1, y1 = comps[0][1]
        ww, hh = x1-x0+1, y1-y0+1
        print(f'  STRICT t=12 bbox x={x0}..{x1} y={y0}..{y1} size={ww}x{hh} width/height={ww/hh:.6f} height/width={hh/ww:.6f} width/full_image={ww/w:.6f}')
# Save a threshold mask most useful for looking at the silhouette.
t=8
mask=(diff>t)|(g<bg[:,None,:].mean(2)-25)
mask[:60]=False; mask[1490:]=False; mask[:,:180]=False; mask[:,850:]=False
Image.fromarray((mask*255).astype('uint8')).save(OUT/'can_subject_mask_t8.png')
(OUT/'segmentation_bounds.json').write_text(json.dumps({'image_size_px':[w,h],'bounds_by_difference_threshold':results},indent=2),encoding='utf-8')
print('PASS saved segmentation_bounds.json and can_subject_mask_t8.png')
