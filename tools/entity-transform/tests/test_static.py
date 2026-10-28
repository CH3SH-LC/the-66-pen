"""Reject misleading static-conversion receipts without accessing a game process."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from static_receipt import validate_success, extension


def fixture():
    pose = dict(localPosition=[1., 2., 3.], rotationDegrees=[0., 0., 0.],
                scale=[1., 1., 1.], worldPosition=[1., 2., 3.])
    p = dict(entityId=7, owner=100, unity=200, parent=300, status=0,
             called=0, mask=0, openCalled=0, readbackVerified=1, before=pose, after=pose)
    capture = dict(status=0, seh=0, mode=0, completed=1, count=1, sceneUnchanged=1, rows=[p])
    row = dict(entityId=7, owner=100, status=0, beforeFlag=0, afterFlag=1, called=1,
               returned=1, attachedBefore=6, attachedAfter=0, component=400, klass=500,
               pendingBefore=0, pendingAfter=0, depthBefore=0, depthAfter=0)
    return dict(status=0, seh=0, stage=5, count=1, completed=1, sceneUnchanged=1,
                mode=1, mutationCalls=1, beforePose=capture, afterPose=copy.deepcopy(capture),
                rows=[row])


class StaticContractTests(unittest.TestCase):
    def test_complete_conversion(self):
        validate_success(fixture(), [dict(entityId=7)])

    def test_reject_incomplete_and_rebound_rows(self):
        for field, value in (('afterFlag', 0), ('beforeFlag', 1), ('called', 0),
                             ('returned', 0), ('attachedAfter', 1), ('pendingAfter', 1),
                             ('depthAfter', 1), ('entityId', 8), ('owner', 101)):
            with self.subTest(field=field):
                r = fixture()
                r['rows'][0][field] = value
                with self.assertRaises(ValueError):
                    validate_success(r, [dict(entityId=7)])

    def test_pose_changes_are_not_success(self):
        r = fixture()
        r['afterPose']['rows'][0]['after']['scale'] = [2., 1., 1.]
        with self.assertRaisesRegex(ValueError, 'POSE_CHANGED'):
            validate_success(r, [dict(entityId=7)])

    def test_native_mutation_is_not_readonly(self):
        r = fixture()
        r['mode'] = 0
        with self.assertRaises(ValueError):
            validate_success(r, [dict(entityId=7)])

    def test_partial_execution_and_scene_change(self):
        for field, value in (('completed', 0), ('sceneUnchanged', 0), ('seh', 1),
                             ('mutationCalls', 2), ('stage', 3)):
            r = fixture()
            r[field] = value
            with self.assertRaises(ValueError):
                validate_success(r, [dict(entityId=7)])

    def test_truncated_binary_refused(self):
        with self.assertRaisesRegex(ValueError, 'RECEIPT_SIZE'):
            extension(bytes(128), 262584)


if __name__ == '__main__':
    unittest.main()
