"""Untextured orthographic projections of exact captured mesh triangles."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from PIL import Image,ImageDraw
from sources import ROOT,OUTPUT,write_json
def sha(raw):return hashlib.sha256(raw).hexdigest()

def draw(row,out):
    data=np.load(ROOT/row['combinedMesh']['npz'],allow_pickle=False);v=data['vertices'];faces=data['triangles'];part=data['facePart']
    eligible=[x['partIndex']for x in row['parts']if x['nonShadowEnabledStaticCandidate']]
    faces=faces[np.isin(part,eligible)]
    if not len(faces):raise ValueError('No non-shadow enabled triangles')
    triangles=v[faces];normal=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);normal/=np.maximum(np.linalg.norm(normal,axis=1)[:,None],1e-12)
    light=np.array([.3,.85,.45]);light/=np.linalg.norm(light);shade=.32+.62*np.abs(normal@light)
    colors=np.column_stack((shade*.75,shade*.85,shade,np.ones(len(shade))))
    low=v[np.unique(faces)].min(axis=0);high=v[np.unique(faces)].max(axis=0)
    fig,axes=plt.subplots(2,2,figsize=(12,10));iso_right=np.array([1.,0.,-1.])/np.sqrt(2);look=np.array([1.,.7,1.]);look/=np.linalg.norm(look);iso_up=np.cross(look,iso_right)
    views=[('Top / XZ',[1,0,0],[0,0,1],[0,1,0]),('Front / XY',[1,0,0],[0,1,0],[0,0,-1]),
        ('Side / ZY',[0,0,1],[0,1,0],[1,0,0]),('Oblique',iso_right,iso_up,look)]
    for ax,(name,right,up,depth)in zip(axes.flat,views):
        basis=np.column_stack((right,up));xy=triangles@basis;z=(triangles@np.asarray(depth)).mean(axis=1);order=np.argsort(z,kind='stable')
        ax.add_collection(PolyCollection(xy[order],facecolors=colors[order],edgecolors='none',rasterized=True))
        points=v[np.unique(faces)]@basis;lo=np.minimum(points.min(axis=0),0);hi=np.maximum(points.max(axis=0),0);pad=max(float(np.max(hi-lo))*.06,.03)
        ax.set(xlim=(lo[0]-pad,hi[0]+pad),ylim=(lo[1]-pad,hi[1]+pad),title=name);ax.set_aspect('equal');ax.grid(alpha=.15)
        ax.plot(0,0,'+',color='#d14c45',markersize=9,markeredgewidth=1.5)
    size=high-low;tid=row.get('templateId');label=tid if tid is not None else row['identityChain']['landmark']
    fig.suptitle(f'{label} | {row["prefabRoot"]["name"]}\nXYZ = {size[0]:.4f} / {size[1]:.4f} / {size[2]:.4f} source units',fontsize=12)
    fig.text(.5,.014,'Original static mesh geometry, untextured. Red + = prefab root. No runtime renderer/collider or material acceptance.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.03,1,.94));fig.savefig(out,dpi=125);plt.close(fig)
    return {'templateId':tid,'path':str(out.relative_to(ROOT)),'sha256':sha(out.read_bytes()),'triangleCount':len(faces),'textureApplied':False,
        'runtimeScreenshot':False,'filter':'MeshRenderer enabled=1 and castShadowsRaw!=3; runtime GameObject activity and LOD unresolved'}

def build():
    if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package')
    index=json.loads((OUTPUT/'geometry-index.json').read_text(encoding='utf8'));folder=OUTPUT/'projections';folder.mkdir(exist_ok=True);rows=[]
    for entry in index['rows']:
        if entry['status']!='captured':continue
        row=json.loads((ROOT/entry['geometry']).read_text(encoding='utf8'));rows.append(draw(row,folder/(str(entry['templateId'])+'.png')))
        print(json.dumps({'projection':entry['templateId']}),flush=True)
    width,height=320,285;cols=6;sheet=Image.new('RGB',(cols*width,((len(rows)+cols-1)//cols)*height),'white');pen=ImageDraw.Draw(sheet)
    for i,r in enumerate(rows):
        im=Image.open(ROOT/r['path']);im.thumbnail((width,height-20));x=(i%cols)*width;y=(i//cols)*height;sheet.paste(im,(x,y));pen.text((x+10,y+height-19),str(r['templateId']),fill='black')
    sheet.save(folder/'contact-sheet.png');write_json(OUTPUT/'projections.json',{'rows':rows,'contactSheet':str((folder/'contact-sheet.png').relative_to(ROOT)),
        'contactSheetSha256':sha((folder/'contact-sheet.png').read_bytes())})

if __name__=='__main__':build()
