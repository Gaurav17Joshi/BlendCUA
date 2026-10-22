from pathlib import Path
import json, sys
import numpy as np
from PIL import Image
for s in (sys.stdout,sys.stderr):
    try:s.reconfigure(encoding='utf-8',errors='replace')
    except Exception:pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
a=np.asarray(Image.open(ROOT/'reference.png').convert('RGB')).astype(float)
h,w=a.shape[:2]; g=a.mean(2); sat=a.max(2)-a.min(2)

def stats(name, arr):
    arr=np.asarray(arr).reshape(-1,3)
    med=np.median(arr,axis=0); q10=np.percentile(arr,10,axis=0); q90=np.percentile(arr,90,axis=0)
    print(f'{name}: n={len(arr)} median={med.round(1).tolist()} p10={q10.round(1).tolist()} p90={q90.round(1).tolist()}')
    return {'n':int(len(arr)),'median':med.tolist(),'p10':q10.tolist(),'p90':q90.tolist()}

out={}
# Background: only far side strips; report separate vertical slabs because the
# product shot has a mild vertical/lighting gradient.
for name,box in [('background_left',(20,250,180,1250)),('background_right',(845,250,1005,1250)),('background_top',(20,80,1005,250)),('background_bottom',(20,1400,1005,1500))]:
    x0,y0,x1,y1=box; out[name]=stats(name,a[y0:y1,x0:x1])
# Matte black label pixels: very dark, low-saturation pixels well inside body,
# excluding the graphic rows and outer shading.
mask_black=(g<35)&(sat<35)
mask_black[:240]=False; mask_black[940:]=False
mask_black[:,:300]=False; mask_black[:,730:]=False
out['black_label']=stats('black_label',a[mask_black])
# Green is selected from the same ratio threshold used for the logo bbox.
mask_green_all=(a[:,:,1]>a[:,:,0]*1.22)&(a[:,:,1]>a[:,:,2]*1.08)&(a[:,:,1]>70)
mask_green=mask_green_all.copy()
mask_green[:220]=False; mask_green[1000:]=False
out['green_claws']=stats('green_claws',a[mask_green])
mask_energy=mask_green_all.copy(); mask_energy[:1100]=False; mask_energy[1220:]=False
out['green_energy']=stats('green_energy',a[mask_energy])
# White printed glyph pixels in the label, ignoring high-sat green.
mask_white=(g>170)&(sat<100); mask_white[:950]=False; mask_white[1380:]=False
mask_white[:,:267]=False; mask_white[:,763:]=False
out['white_label']=stats('white_label',a[mask_white])
# Silver top/bottom material: neutral/high-value pixels in narrow centre windows.
mask_silver=(sat<45)&(g>110)
mask_top=mask_silver.copy(); mask_top[:80]=False; mask_top[165:]=True
# easier explicit slices; body reflections are not included in these bands
out['top_silver']=stats('top_silver',a[90:153,285:747][mask_silver[90:153,285:747]])
out['bottom_silver']=stats('bottom_silver',a[1419:1469,270:760][mask_silver[1419:1469,270:760]])
(OUT/'reference_color_samples.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print('PASS saved reference_color_samples.json')
