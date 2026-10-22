from pathlib import Path
import json, sys
import numpy as np
from PIL import Image
for s in (sys.stdout,sys.stderr):
    try:s.reconfigure(encoding='utf-8',errors='replace')
    except Exception:pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
a=np.asarray(Image.open(ROOT/'reference.png').convert('RGB')).astype(float)
g=a.mean(2); sat=a.max(2)-a.min(2); h,w=g.shape
# Every region is an explicit search window; the mask is then resolved by channel
# thresholds. This avoids reading a bounding box from the displayed crop.
def box(name, mask, y0,y1,x0=250,x1=780):
    m=mask.copy(); m[:y0]=False; m[y1+1:]=False; m[:,:x0]=False; m[:,x1+1:]=False
    yy,xx=np.where(m)
    if not len(xx):
        print(name,'NONE'); return None
    b=[int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())]
    print(name,'bbox',b,'size',(b[2]-b[0]+1,b[3]-b[1]+1),'norm',(round(b[0]/w,6),round(b[1]/h,6),round(b[2]/w,6),round(b[3]/h,6)))
    return b
white=(g>160)&(sat<100)
green=(a[:,:,1]>a[:,:,0]*1.18)&(a[:,:,1]>a[:,:,2]*1.03)&(a[:,:,1]>65)
# Stay a few pixels inside the silhouette to keep antialiased metal/background
# edges out of the label-ink bbox.
boxes={
 'top_white': box('top_white',white,130,210,280,750),
 'monster_white': box('monster_white',white,950,1140,280,750),
 'energy_green_or_white': box('energy_green_or_white',green|white,1130,1210,280,750),
 'lower_white': box('lower_white',white,1220,1380,280,750),
 'claw_green': box('claw_green',green,220,1000,267,763),
}
(OUT/'graphic_boxes.json').write_text(json.dumps({'image_size_px':[w,h],'boxes':boxes},indent=2),encoding='utf-8')
print('PASS saved graphic_boxes.json')
