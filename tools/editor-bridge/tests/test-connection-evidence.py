import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('connection_evidence', Path(__file__).resolve().parents[1] / 'connection-evidence.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(pid, local, remote, state='Established', address='127.0.0.1'):
    return dict(OwningProcess=pid, State=state, LocalAddress=address,
                LocalPort=local, RemoteAddress=address, RemotePort=remote)


class ConnectionTests(unittest.TestCase):
    def test_self_connection_is_not_game(self):
        result = module.classify([row(1, 59214, 59214), row(2, 57088, 0, 'Listen')], 1, 2)
        self.assertTrue(result['editorSelfConnectionObserved'])
        self.assertFalse(result['reciprocalPairObserved'])

    def test_reciprocal_pair_is_only_transport_evidence(self):
        result = module.classify([row(1, 100, 200), row(2, 200, 100)], 1, 2)
        self.assertTrue(result['reciprocalPairObserved'])
        self.assertFalse(result['protocolHandshakeVerified'])
        self.assertFalse(result['currentLevelVerified'])

    def test_wrong_owner_and_one_sided_pair(self):
        self.assertFalse(module.classify([row(1, 100, 200), row(3, 200, 100)], 1, 2)['reciprocalPairObserved'])

    def test_pending_pair(self):
        self.assertFalse(module.classify([row(1, 100, 200, 'SynSent'), row(2, 200, 100)], 1, 2)['reciprocalPairObserved'])

    def test_ipv6_loopback(self):
        self.assertTrue(module.classify([row(1, 100, 200, address='::1'), row(2, 200, 100, address='::1')], 1, 2)['reciprocalPairObserved'])

    def test_external_rows_excluded(self):
        self.assertFalse(module.classify([row(1, 100, 200, address='192.0.2.1'), row(2, 200, 100, address='192.0.2.1')], 1, 2)['reciprocalPairObserved'])

    def test_same_pid_rejected(self):
        with self.assertRaises(ValueError):
            module.classify([], 1, 1)


if __name__ == '__main__':
    unittest.main()
