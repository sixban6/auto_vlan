"""
orchestrator.py 测试 — 自动端口分配逻辑。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import NetworkOrchestrator
from hw_detect import HardwareInfo, SwitchInfo
from models import NetworkConfig, WifiConfig
from roles import create_default_registry
from uci import UciExecutor


class TestAutoAllocatePorts(unittest.TestCase):
    """_auto_allocate_ports 端口分配逻辑"""

    def _make_orchestrator(self):
        uci = UciExecutor(dry_run=True)
        registry = create_default_registry()
        return NetworkOrchestrator(uci, registry)

    def _make_swconfig_hw(self, lan_ports):
        sw = SwitchInfo(
            name="switch0", cpu_port=5, cpu_interface="eth0",
            lan_ports=lan_ports, wan_port=0,
        )
        return HardwareInfo(mode="swconfig", wan_interface="eth0",
                            lan_ports=[], switch=sw)

    def _make_dsa_hw(self, lan_ports):
        return HardwareInfo(mode="dsa", wan_interface="eth0",
                            lan_ports=lan_ports)

    def _make_nets(self, count, with_ports=False):
        """创建 count 个网络 (VLAN 1, 5, 3, ...)"""
        vlan_ids = [1, 5, 3, 7, 9]
        names = ["lan", "home", "iot", "guest", "test"]
        roles = ["proxy", "clean", "isolate", "clean", "isolate"]
        nets = []
        for i in range(count):
            nets.append(NetworkConfig(
                name=names[i], vlan_id=vlan_ids[i], role=roles[i],
                subnet=f"192.168.{vlan_ids[i]}.1", netmask="255.255.255.0",
                ports=["lan1"] if with_ports else [],
            ))
        return nets

    # ---- Swconfig 分配 ----

    def test_swconfig_3_ports_3_nets(self):
        """Swconfig: 3 口 3 网络 → 1对1, 无剩余"""
        orc = self._make_orchestrator()
        hw = self._make_swconfig_hw([1, 2, 3])
        nets = self._make_nets(3)

        orc._auto_allocate_ports(nets, hw)

        self.assertEqual(nets[0].ports, ["lan1"])  # lan → port 1
        self.assertEqual(nets[1].ports, ["lan2"])  # home → port 2
        self.assertEqual(nets[2].ports, ["lan3"])  # iot → port 3

    def test_swconfig_4_ports_3_nets_remainder_to_vlan1(self):
        """Swconfig: 4 口 3 网络 → 剩余 1 口归 VLAN 1"""
        orc = self._make_orchestrator()
        hw = self._make_swconfig_hw([1, 2, 3, 4])
        nets = self._make_nets(3)

        orc._auto_allocate_ports(nets, hw)

        # lan 分到 port 1, home 到 port 2, iot 到 port 3
        # 剩余 port 4 归 VLAN 1 (lan)
        self.assertEqual(nets[0].ports, ["lan1", "lan4"])
        self.assertEqual(nets[1].ports, ["lan2"])
        self.assertEqual(nets[2].ports, ["lan3"])

    def test_swconfig_2_ports_3_nets_insufficient(self):
        """Swconfig: 2 口 3 网络 → 第三个网络无端口 (WiFi only)"""
        orc = self._make_orchestrator()
        hw = self._make_swconfig_hw([1, 2])
        nets = self._make_nets(3)

        orc._auto_allocate_ports(nets, hw)

        self.assertEqual(nets[0].ports, ["lan1"])
        self.assertEqual(nets[1].ports, ["lan2"])
        self.assertEqual(nets[2].ports, [])  # WiFi only

    def test_manual_ports_skip_allocation(self):
        """手动指定 ports 的网络应跳过自动分配"""
        orc = self._make_orchestrator()
        hw = self._make_swconfig_hw([1, 2, 3])
        nets = self._make_nets(2, with_ports=True)  # 都有 ports=["lan1"]

        orc._auto_allocate_ports(nets, hw)

        # 网络都有 ports → 无 target → 不分配
        # 但剩余端口仍归 VLAN 1 (nets[0])
        self.assertEqual(nets[0].ports, ["lan1", "lan1", "lan2", "lan3"])

    def test_zero_ports_skips(self):
        """0 口 → 跳过分配"""
        orc = self._make_orchestrator()
        hw = self._make_swconfig_hw([])
        nets = self._make_nets(2)

        orc._auto_allocate_ports(nets, hw)

        self.assertEqual(nets[0].ports, [])
        self.assertEqual(nets[1].ports, [])

    # ---- DSA 分配 ----

    def test_dsa_3_ports_3_nets(self):
        """DSA: 3 口 3 网络"""
        orc = self._make_orchestrator()
        hw = self._make_dsa_hw(["eth1", "eth2", "eth3"])
        nets = self._make_nets(3)

        orc._auto_allocate_ports(nets, hw)

        self.assertEqual(nets[0].ports, ["lan1"])
        self.assertEqual(nets[1].ports, ["lan2"])
        self.assertEqual(nets[2].ports, ["lan3"])

    def test_dsa_4_ports_2_nets_remainder_to_vlan1(self):
        """DSA: 4 口 2 网络 → 剩余归 VLAN 1"""
        orc = self._make_orchestrator()
        hw = self._make_dsa_hw(["eth1", "eth2", "eth3", "eth4"])
        nets = self._make_nets(2)

        orc._auto_allocate_ports(nets, hw)

        # lan → eth1 (lan1), home → eth2 (lan2)
        # 剩余 eth3 (lan3), eth4 (lan4) 归 VLAN 1 (lan)
        self.assertEqual(nets[0].ports, ["lan1", "lan3", "lan4"])
        self.assertEqual(nets[1].ports, ["lan2"])

    def test_single_net_gets_all_ports(self):
        """单网络 → 分到 1 个端口 + 剩余全归 VLAN 1"""
        orc = self._make_orchestrator()
        hw = self._make_swconfig_hw([1, 2, 3, 4])
        nets = self._make_nets(1)

        orc._auto_allocate_ports(nets, hw)

        self.assertEqual(nets[0].ports, ["lan1", "lan2", "lan3", "lan4"])


# ================================================================
# UciExecutor 模式测试
# ================================================================
class TestUciExecutor(unittest.TestCase):

    def test_dry_run_mode(self):
        """Dry-run 模式不真正执行"""
        uci = UciExecutor(dry_run=True)
        self.assertTrue(uci.is_dry_run)
        self.assertFalse(uci.is_export)
        # 不应崩溃
        uci.set("network.lan", "interface")

    def test_export_mode(self):
        """Export 模式应收集命令"""
        uci = UciExecutor(export=True)
        self.assertTrue(uci.is_export)
        uci.set("network.lan", "interface")
        uci.add("network", "switch_vlan")
        # query 应返回 None
        self.assertIsNone(uci.query("get network.lan"))

    def test_export_write_script(self):
        """Export 模式写脚本"""
        import tempfile
        uci = UciExecutor(export=True)
        uci.set("network.lan", "interface")

        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w") as f:
            path = f.name

        uci.write_script(path)

        with open(path, "r") as f:
            content = f.read()

        self.assertIn("#!/bin/sh", content)
        self.assertIn("uci set", content)
        os.unlink(path)

    def test_non_export_cannot_write_script(self):
        """非 export 模式调用 write_script 应报错"""
        uci = UciExecutor(dry_run=True)
        with self.assertRaises(RuntimeError):
            uci.write_script("/tmp/test.sh")


if __name__ == "__main__":
    unittest.main()
