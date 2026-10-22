"""Consolidated navigation checks against the captured native catalog."""
import json
import unittest
from .catalog import Catalog, OUTPUT, sha
from .discovery import Discovery


class NavigationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Catalog()
        cls.d = Discovery()

    def test_complete_native_identity_and_menu_provenance(self):
        rows = self.d.read('routes.json')
        native = {n['key']: n for n in self.c.nodes}
        self.assertEqual(len(rows), 929)
        self.assertEqual({n['key'] for n in rows}, set(native))
        self.assertEqual(self.d.index['catalogSha256'], sha(OUTPUT/'catalog.json'))
        for row in rows:
            n = native[row['key']]
            self.assertEqual(row['graphKind'], n['graphKind'])
            self.assertEqual(row['menuVisibility'], n['menuVisibility'])
            self.assertTrue(row['clusters'])
            self.assertNotIn('ports', row)
            if not n['menuPaths']:
                self.assertIn('not-public-menu', row['evidence'])

    def test_groups_and_special_mechanisms(self):
        self.assertEqual(len(self.d.index['groups']), 7)
        self.assertEqual(sum(g['count'] for g in self.d.index['groups']), 929)
        for name in ('assets', 'composite'):
            g = self.d.group(name)
            self.assertEqual(g['count'], 0)
            self.assertIn('mechanism', g)
            self.assertFalse(g['builtin'])
        self.assertIn('interaction', [c['id'] for c in self.d.group('event')['clusters']])

    def test_focused_route_without_detail_flood(self):
        for query, cluster in [('靠近 NPC 打开商店', 'interaction'), ('靠近 NPC 打开商店', 'shop'), ('玩家能力', 'skills'), ('种田', 'farming'), ('出售', 'shop')]:
            r = self.d.route(query)
            self.assertIn(cluster, [c['id'] for c in r['matches']])
            self.assertLessEqual(len(r['matches']), 5)
            self.assertLess(len(json.dumps(r, ensure_ascii=False)), 6000)
            self.assertNotIn('ports', r)

    def test_cross_group_lookup_and_paging(self):
        c = self.d.cluster('interaction', 20000, 'event')
        self.assertIn(307, [n['definitionId'] for n in c['nodes']])
        self.assertTrue(all(n['family']=='事件节点' and n['graphKind']==20000 for n in c['nodes']))
        all_nodes = self.d.read('clusters/math.json')['nodes']
        seen=[]; offset=0
        while offset is not None:
            page=self.d.cluster('math', offset=offset, limit=7)
            seen.extend(n['key'] for n in page['nodes']);offset=page['nextOffset']
        self.assertEqual(seen, [n['key'] for n in all_nodes])
        self.assertEqual(len(seen),len(set(seen)))

    def test_farming_recipe_contains_real_event_not_pause(self):
        c=self.d.cluster('farming',20000)
        ids={n['definitionId'] for n in c['nodes']}
        self.assertTrue({83,307,259,702,707,690,686} <= ids)
        self.assertNotIn(80,ids)
        for n in c['nodes']:
            self.assertEqual(n['name'],self.c.require(20000,n['definitionId'])['name'])
        self.assertFalse(c['runtimeVerified'])


if __name__=='__main__':
    unittest.main()
