"""Consolidated checks against real source fixtures; no editor calls."""
import json
import unittest

from .catalog import Catalog, LIVE, OUTPUT, ROOT, message, scalar, sha
from .recipes import compatible_edge, recipe, tab_shop_example, value_candidate


class NativeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.live = json.loads(LIVE.read_text(encoding='utf-8'))

    def test_complete_live_domain_and_all_ports(self):
        c = self.catalog
        self.assertEqual(c.data['stats']['byGraphKind'], {'20000': 500, '20001': 122, '20002': 197, '20007': 110})
        self.assertEqual(len({n['definitionId'] for n in c.nodes}), 810)
        self.assertEqual(c.data['discrepancies'], [])
        self.assertEqual(c.data['resourceVariantsOutsideLive'], [])
        self.assertEqual(c.data['menuReferencesOutsideLive'], [])
        for n in self.live['nodes']:
            node = c.require(n['category'][1], n['id'])
            self.assertEqual([p['live'] for p in node['ports']], n['definition']['pins'])
            for p in node['ports']:
                self.assertIsNotNone(p['resourceRaw'])
                sig = message(p['resourceRaw'], 3)
                self.assertEqual((scalar(sig, 1), scalar(sig, 2)), (p['live']['kernelKind'], p['live']['kernelIndex']))

    def test_installed_resources_still_match(self):
        sources = self.catalog.data['evidence']['installed']
        self.assertEqual(len(sources), 812)
        for s in sources:
            self.assertEqual(sha(s['path']), s['sha256'], s['path'])

    def test_client_kernel_index_is_not_authoring_index(self):
        n = self.catalog.require(20002, 200041)
        p = next(p for p in n['ports'] if p['key'] == '3:0')
        self.assertEqual(p['name'], '目标实体')
        self.assertEqual(p['resourceKernelPin'], '3:1')
        self.assertEqual(p['descriptor']['storageKind'], 0)
        n = self.catalog.require(20002, 200056)
        p = next(p for p in n['ports'] if p['key'] == '3:0')
        self.assertEqual(p['resourceKernelPin'], '3:1')
        self.assertEqual(p['descriptor']['storageKind'], 6)
        self.assertEqual(p['descriptor']['serverParamType'], 5)

    def test_timer_boolean_uses_enum_and_real_options(self):
        candidate = value_candidate(self.catalog, 20000, 79, 2, {'uint': 1})
        self.assertEqual(candidate['slot'], 'enum')
        self.assertEqual(candidate['expect'], {'serverParamType': 4, 'genericId': 4})
        with self.assertRaisesRegex(ValueError, 'STORAGE_PAYLOAD'):
            value_candidate(self.catalog, 20000, 79, 2, {'bool': True})
        with self.assertRaisesRegex(ValueError, 'ENUM_VALUE'):
            value_candidate(self.catalog, 20000, 79, 2, {'uint': 99})
        with self.assertRaisesRegex(ValueError, 'INT32'):
            value_candidate(self.catalog, 20000, 702, 2, {'int': 2 ** 31})

    def test_generic_dict_is_not_a_scalar_and_retains_dynamic_rules(self):
        n = self.catalog.require(20000, 1788)
        self.assertTrue(n['dynamicPortsRaw'])
        p = next(p for p in n['ports'] if p['key'] == '3:1')
        self.assertGreater(len(p['descriptor']['genericChoices']), 1)
        with self.assertRaisesRegex(ValueError, 'CONCRETE_SUPPORTED'):
            value_candidate(self.catalog, 20000, 1788, 1, {'int': 1})

    def test_stores_are_category_specific(self):
        for kind, count in ((20000, 500), (20001, 122), (20002, 197), (20007, 110)):
            store = self.catalog.contract_store(kind)
            self.assertEqual(len(store), count)
            self.assertTrue(all(store.require(i).graph_kind == kind for i in store))
        with self.assertRaisesRegex(ValueError, 'NODE_NOT_IN_CATEGORY'):
            self.catalog.require(20001, 702)

    def test_shop_event_recipe_uses_character_owner_and_actual_ports(self):
        from tools.gameplan.plan import GraphPlan
        example = tab_shop_example(self.catalog)
        plan = GraphPlan(example['name'], example['graphKind'])
        for i, node in enumerate(example['plan']['nodes']):
            plan.add(f'n{i}', node['definitionId'])
        for edge in example['plan']['edges']:
            plan.wire(f'n{edge["from"]}', edge['fromKind'], edge['fromIndex'],
                      f'n{edge["to"]}', edge['toKind'], edge['toIndex'])
        plan.const('n2', 2, 1, 'int')
        plan.validate(self.catalog.contract_store(20000))
        event = self.catalog.require(20000, 307)
        self.assertIn('触发选项卡时的角色实体', str(event['official']))
        with self.assertRaisesRegex(ValueError, 'CONCRETE_TYPE_MISMATCH'):
            compatible_edge(self.catalog, 20000, 307, '4:2', 702, '3:0')
        with self.assertRaisesRegex(ValueError, 'DIRECTION_MISMATCH'):
            compatible_edge(self.catalog, 20000, 307, '2:0', 702, '3:0')
        with self.assertRaisesRegex(ValueError, 'PORT_NOT_DECLARED'):
            compatible_edge(self.catalog, 20000, 307, '4:90', 702, '3:0')

    def test_recipes_cover_every_variant_without_runtime_claim(self):
        all_recipes = json.loads((OUTPUT / 'recipes.json').read_text(encoding='utf-8'))
        self.assertEqual({r['definitionKey'] for r in all_recipes}, {n['key'] for n in self.catalog.nodes})
        self.assertTrue(all(not r['nativeMutationsPerformed'] and not r['runtimeVerified'] for r in all_recipes))
        self.assertEqual(recipe(self.catalog, 20000, 307)['nativeAddMethod'], 'A35XuAK09QD')

    def test_html_contains_exact_catalog_and_no_external_scripts(self):
        import re
        source = (OUTPUT / 'index.html').read_text(encoding='utf-8')
        payload = re.search(r'<script type="application/json" id="data">(.*?)</script>', source, re.S).group(1)
        self.assertEqual(json.loads(payload)['stats'], self.catalog.data['stats'])
        self.assertNotRegex(source, r'<script[^>]+src=')
        self.assertNotIn('fetch(', source)


if __name__ == '__main__':
    unittest.main()
