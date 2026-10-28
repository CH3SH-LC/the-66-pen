"""Deferred batch checks. Run only after the parent's complete-development gate."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from geometry import Mesh, component_candidates, fit_registration, read_glb, read_obj, sample_surface, transform
from reference_cli import PROJECT, frame_matrix, project_path
from ground_reference import named_grid, subset
from shoreline_registration import contour_segments


class ReferenceChecks(unittest.TestCase):
    def setUp(self):
        root=PROJECT/'.runtime/mondstadt/rework-20261017/reference3d/test-scratch'
        root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.root=Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def obj(self,text):
        p=self.root/'mesh.obj';p.write_text(text,encoding='utf-8');return read_obj(p)

    def triangle(self,y=0):
        return Mesh(np.array([[0,y,0],[10,y,0],[0,y,10]],float),np.array([[0,1,2]]),['g'],np.array([0]))

    def test_obj_negative_indices_and_groups(self):
        m=self.obj('v 0 0 0\nv 1 0 0\nv 0 0 1\ng roof\nf -3/-1 -2/-1 -1/-1\n')
        np.testing.assert_array_equal(m.faces,[[0,1,2]])
        self.assertEqual(m.groups[m.face_groups[0]],'roof')

    def test_obj_rejects_concave_polygon_shortcut(self):
        with self.assertRaisesRegex(ValueError,'nontriangle'):
            self.obj('v 0 0 0\nv 1 0 0\nv 0 0 1\nv -1 0 0\nf 1 2 3 4\n')

    def test_obj_rejects_invalid_index(self):
        with self.assertRaisesRegex(ValueError,'range'):
            self.obj('v 0 0 0\nv 1 0 0\nv 0 0 1\nf 1 2 4\n')

    def test_nonfinite_rejected(self):
        with self.assertRaisesRegex(ValueError,'Nonfinite'):
            self.obj('v nan 0 0\nv 1 0 0\nv 0 0 1\nf 1 2 3\n')

    def test_affine_transform(self):
        matrix=np.eye(4);matrix[0,0]=2;matrix[:3,3]=[5,9,-2]
        m=transform(self.triangle(),matrix)
        np.testing.assert_array_equal(m.vertices[1],[25,9,-2])

    def test_world_and_raw_distinction(self):
        row={'role':'city-geometry','manifestPosition':{'x':2275,'y':263,'z':-783}}
        np.testing.assert_array_equal(frame_matrix(row,self.triangle(),'viewer')[:3,3],[-1251,263,-783])
        np.testing.assert_array_equal(frame_matrix(row,self.triangle(),'raw')[:3,3],[0,0,0])

    def test_two_height_layers_and_holes(self):
        a,b=self.triangle(3),self.triangle(13)
        m=Mesh(np.r_[a.vertices,b.vertices],np.r_[a.faces,b.faces+3],['g'],np.array([0,0]))
        grid=sample_surface(m,[0,10,0,10],5)
        self.assertEqual(grid['top'][0,0],13);self.assertEqual(grid['bottom'][0,0],3)
        self.assertEqual(grid['top_face'][0,0],1);self.assertEqual(grid['bottom_face'][0,0],0)
        self.assertTrue(np.isnan(grid['top'][2,2]))

    def test_sloping_triangle_interpolation(self):
        m=self.triangle();m.vertices[1,1]=10
        grid=sample_surface(m,[0,10,0,10],5)
        self.assertAlmostEqual(grid['top'][0,1],5)
        self.assertAlmostEqual(grid['top_slope_degrees'][0,1],45)

    def test_welding_does_not_invent_buildings(self):
        m=Mesh(np.array([[0,0,0],[1,0,0],[0,0,1],[1,0,0],[1,0,1],[0,0,1]],float),
               np.array([[0,1,2],[3,4,5]]),['g'],np.array([0,0]))
        rows=component_candidates(m)
        self.assertEqual(len(rows),1);self.assertFalse(rows[0]['confirmedBuilding'])
        self.assertEqual(rows[0]['convexFootprintArea'],1)

    def test_registration_nonzero_residual(self):
        src=[[0,0],[10,0],[0,10],[10,10]]
        anchors=[dict(id=str(i),sourceXZ=p,officialGlobalPixel=[100+2*p[0],200+2*p[1]]) for i,p in enumerate(src)]
        anchors[-1]['officialGlobalPixel'][1]+=1
        r=fit_registration(anchors)
        self.assertGreater(r['rmsePixels'],0);self.assertEqual(len(r['leaveOneOutPixels']),4)

    def test_registration_rejects_collinear(self):
        with self.assertRaisesRegex(ValueError,'Collinear'):
            fit_registration([dict(id=str(i),sourceXZ=[i,0],officialGlobalPixel=[2*i,0]) for i in range(3)])

    def test_outside_output_rejected(self):
        with self.assertRaisesRegex(ValueError,'inside project'): project_path(PROJECT.parent/'escape.json')

    def test_named_grid_spans_and_last_sample_are_unambiguous(self):
        grid={'x':np.arange(-1885,-619,5),'z':np.arange(-1570,-199,5)}
        metadata=named_grid(grid,5)
        self.assertEqual(metadata['xSpan'],1265)
        self.assertEqual(metadata['zSpan'],1370)
        self.assertEqual(metadata['lastSample'],{'x':-620.0,'z':-200.0})
        self.assertEqual(metadata['exampleIndex']['x'],-1875)

    def test_excluded_roof_does_not_affect_selected_ground(self):
        ground,roof=self.triangle(2),self.triangle(20)
        all_mesh=Mesh(np.r_[ground.vertices,roof.vertices],np.r_[ground.faces,roof.faces+3],['g'],np.array([0,0]))
        selected=subset(all_mesh,[0],'base-terrain')
        self.assertEqual(sample_surface(selected,[0,10,0,10],5)['top'][0,0],2)

    def test_shoreline_contour_comes_from_triangle_geometry(self):
        vertices=np.array([[0,0,0],[10,10,0],[0,0,10]],float)
        segments=contour_segments(vertices,np.array([[0,1,2]]),5)
        self.assertEqual(segments.shape,(1,2,2))
        np.testing.assert_allclose(segments[0,:,0],[5,5])
        np.testing.assert_allclose(sorted(segments[0,:,1]),[0,5])

    def glb(self,external=False):
        vertices=np.array([[0,0,0],[1,0,0],[0,0,1]],dtype='<f4').tobytes()
        doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(vertices)}],
             'bufferViews':[{'buffer':0,'byteLength':len(vertices)}],
             'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3'}],
             'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
             'nodes':[{'mesh':0,'translation':[4,5,6],'scale':[2,2,2]}],
             'scenes':[{'nodes':[0]}],'scene':0}
        if external: doc['buffers'][0]['uri']='https://example.com/x'
        js=json.dumps(doc).encode();js+=b' '*((-len(js))%4)
        blob=struct.pack('<4sII',b'glTF',2,12+8+len(js)+8+len(vertices))+struct.pack('<II',len(js),0x4e4f534a)+js+struct.pack('<II',len(vertices),0x004e4942)+vertices
        p=self.root/'mesh.glb';p.write_bytes(blob);return p

    def test_glb_node_transform(self):
        m=read_glb(self.glb());np.testing.assert_array_equal(m.vertices[1],[6,5,6])

    def test_glb_external_buffer_never_fetched(self):
        with self.assertRaisesRegex(ValueError,'External'): read_glb(self.glb(True))


if __name__=='__main__': unittest.main()
