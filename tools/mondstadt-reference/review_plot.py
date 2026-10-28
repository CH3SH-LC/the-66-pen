"""Plot original official tiles and extracted source geometry for anchor review.

This produces offline scientific comparison figures, not game screenshots.
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
import numpy as np
from reference_cli import PROJECT


def main():
    out=PROJECT/'data/mondstadt/reference3d'
    source=PROJECT/'.runtime/mondstadt/rework-20261017/reference-source'
    fig,ax=plt.subplots(figsize=(14,14))
    for x in (94,95):
        for y in (34,35):
            image=plt.imread(source/f'{x}_{y}_P0.png')
            ax.imshow(image,extent=[x*256,(x+1)*256,(y+1)*256,y*256])
    ax.set_xlim(24064,24576);ax.set_ylim(9216,8704)
    ax.set_xticks(np.arange(24075,24576,25));ax.set_yticks(np.arange(8725,9216,25))
    ax.tick_params(axis='x',labelrotation=90);ax.grid(alpha=.45,linewidth=.6)
    ax.set_title('Official original map tiles; global pixel axes, 25-pixel grid')
    fig.savefig(out/'official-anchor-review.png',dpi=180,bbox_inches='tight');plt.close(fig)
    d=np.load(out/'extracted-viewer/mondstadt-city-lod0.npz');v=d['vertices'];f=d['faces']
    t=v[f];plot=t[:,:,[2,0]].copy();plot[:,:,0]*=-1
    order=np.argsort(t[:,:,1].mean(axis=1));fig,ax=plt.subplots(figsize=(14,14))
    patches=PolyCollection(plot[order],array=t[order,:,1].mean(axis=1),cmap='terrain',linewidths=0)
    ax.add_collection(patches);ax.autoscale_view();ax.invert_yaxis();ax.set_aspect('equal')
    rows=json.loads((out/'extracted-viewer/city-components.json').read_text(encoding='utf-8'))['candidates']
    ids=[111,287,288,289,290,291,292,293,294,295,441,568,570,567,566]
    for row in rows:
        if row['candidateId'] not in ids:continue
        lo,hi=np.array(row['aabbMin']),np.array(row['aabbMax']);c=(lo+hi)/2
        ax.plot(-c[2],c[0],'r+',markersize=10)
        ax.text(-c[2]+2,c[0]+2,f'{row["candidateId"]} ({c[0]:.1f},{c[2]:.1f})',fontsize=7,
                bbox={'facecolor':'white','alpha':.8,'edgecolor':'none','pad':.3})
    ax.set_xlabel('-viewer Z');ax.set_ylabel('viewer X (inverted display)')
    ax.set_title('True city HLOD component centres; candidate controls require semantic match')
    ax.grid(alpha=.4);fig.savefig(out/'geometry-anchor-review.png',dpi=180,bbox_inches='tight');plt.close(fig)


if __name__=='__main__': main()
