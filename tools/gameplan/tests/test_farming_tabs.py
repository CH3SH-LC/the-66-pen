import unittest
from tools.gameplan.demo import farming_tabs as t
from tools.gameplan.demo.farming_manual import _type_contract
from tools.gameplan.tests.test_farm_interaction import FarmEvaluator

class NativeTabsBehavior(unittest.TestCase):
    def model(self,shop=False):
        m=FarmEvaluator(t.shop_plan() if shop else t.farm_plan())
        m.own='stall' if shop else 'soil';m.character_owners={'character':'player'}
        m.inventory[('character',t.CONFIG.seed_id)]=2
        m.option_cards={(m.own,1):True,(m.own,2):False};return m
    def select(self,m,index,host=None):
        m.fire('selected',{0:host or m.own,1:123,2:index,3:'character'})
    def test_native_menu_full_cycle_and_wrong_stale_options(self):
        m=self.model();self.select(m,2);self.assertFalse(m.attempts)
        self.select(m,1);self.assertEqual((m.stage,m.quantity(t.CONFIG.seed_id)),(1,1))
        self.assertEqual(m.option_cards,{('soil',1):False,('soil',2):False})
        self.select(m,1);self.select(m,2);self.assertEqual(len(m.attempts),1)
        self.assertEqual(m.timers[0][0],'soil');m.mature(owner='player');self.assertEqual(m.stage,1)
        m.mature(owner='soil');self.assertEqual(m.option_cards,{('soil',1):False,('soil',2):True})
        self.select(m,1);self.assertEqual(m.stage,2)
        self.select(m,2);self.assertEqual((m.stage,m.quantity(t.CONFIG.crop_id)),(0,1))
        self.select(m,2);self.assertEqual(m.quantity(t.CONFIG.crop_id),1)
        self.assertEqual(m.option_cards,{('soil',1):True,('soil',2):False})
    def test_bag_failure_preserves_harvest_and_foreign_host_cannot_act(self):
        m=self.model();self.select(m,1,host='foreign');self.assertFalse(m.attempts)
        self.select(m,1);m.mature(owner='soil');m.zero_delta.add(t.CONFIG.crop_id)
        self.select(m,2);self.assertEqual((m.stage,m.quantity(t.CONFIG.crop_id)),(2,0))
        self.assertTrue(m.option_cards[('soil',2)])
        m.zero_delta.clear();self.select(m,2);self.assertEqual(m.quantity(t.CONFIG.crop_id),1)
    def test_visible_stall_opens_original_commerce_for_selecting_player(self):
        m=self.model(shop=True);self.select(m,2);self.select(m,1,host='foreign');self.assertFalse(m.opened_shops)
        self.select(m,1);self.assertEqual(m.opened_shops,[('player','shop',1)])
    def test_complete_plans_resolve_native_types_and_fit_dispatch(self):
        for plan,host in [(t.shop_plan(),t.SHOP_HOST),(t.farm_plan(),t.FARM_HOST)]:
            _type_contract(plan);t.package(plan,host)

if __name__=='__main__':unittest.main()
