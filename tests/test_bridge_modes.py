"""
bridge_modes.py 测试 — DSA 和 Swconfig 的 VLAN/接口配置。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge_modes import (
    DsaBridgeMode,
    SwconfigBridgeMode,
    create_bridge_mode,
    _resolve_ports,
)
from hw_detect import HardwareInfo, SwitchInfo
from models import NetworkConfig, WifiConfig
from uci import UciExecutor


class RecordingUci(UciExecutor):
    """记录所有 UCI 命令的执行器"""

    def __init__(self):
        super().__init__(dry_run=True)
        self.commands: list[str] = []

    def run(self, command: str) -> None:
        self.commands.append(f"uci {command}")


# ================================================================
# 端口解析测试
# ================================================================
class TestResolvePorts(unittest.TestCase):
    """_resolve_ports 辅助函数"""

    def test_swconfig_numeric_direct_match(self):
        """Swconfig: lan2 → port 2 (直接值匹配)"""
        result = _resolve_ports(["lan2"], [1, 2, 3])
        self.assertEqual(result, [(2, False)])

    def test_swconfig_tagged_port(self):
        """Swconfig: lan2:t → port 2 (tagged)"""
        result = _resolve_ports(["lan2:t"], [1, 2, 3])
        self.assertEqual(result, [(2, True)])

    def test_swconfig_raw_number(self):
        """Swconfig: '2' → port 2 (直接数字)"""
        result = _resolve_ports(["2"], [1, 2, 3])
        self.assertEqual(result, [(2, False)])

    def test_dsa_index_match(self):
        """DSA: lan1 → index 0 → eth1"""
        result = _resolve_ports(["lan1"], ["eth1", "eth2", "eth3"])
        self.assertEqual(result, [("eth1", False)])

    def test_dsa_direct_match(self):
        """DSA: eth2 → 直接匹配"""
        result = _resolve_ports(["eth2"], ["eth1", "eth2", "eth3"])
        self.assertEqual(result, [("eth2", False)])

    def test_dsa_tagged(self):
        """DSA: lan1:t → tagged"""
        result = _resolve_ports(["lan1:t"], ["eth1", "eth2"])
        self.assertEqual(result, [("eth1", True)])

    def test_out_of_range(self):
        """超出范围的端口应被忽略 (打印警告)"""
        result = _resolve_ports(["lan10"], [1, 2, 3])
        self.assertEqual(result, [])

    def test_multiple_ports(self):
        """多端口混合"""
        result = _resolve_ports(["lan1", "lan3:t"], [1, 2, 3])
        self.assertEqual(result, [(1, False), (3, True)])


# ================================================================
# DSA 桥接模式测试
# ================================================================
class TestDsaBridgeMode(unittest.TestCase):
    """DSA 模式的配置生成"""

    def _make_hw(self, ports=None):
        return HardwareInfo(
            mode="dsa",
            wan_interface="eth0",
            lan_ports=ports or ["eth1", "eth2", "eth3"],
        )

    def test_configure_base_creates_bridge(self):
        """configure_base 应创建 br-lan 网桥"""
        uci = RecordingUci()
        hw = self._make_hw()
        mode = DsaBridgeMode()
        mode.configure_base(uci, hw)

        cmds = " ".join(uci.commands)
        self.assertIn("network.lan_dev", cmds)
        self.assertIn("br-lan", cmds)
        self.assertIn("bridge", cmds)
        self.assertIn("vlan_filtering", cmds)

    def test_configure_vlan_with_ports(self):
        """configure_vlan 应正确添加端口"""
        uci = RecordingUci()
        hw = self._make_hw()
        mode = DsaBridgeMode()
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
            ports=["lan1"],
        )
        mode.configure_vlan(uci, net, hw)

        cmds = " ".join(uci.commands)
        self.assertIn("bridge-vlan", cmds)
        self.assertIn("vlan", cmds)

    def test_configure_interface(self):
        """configure_interface 应绑定 br-lan.VID"""
        uci = RecordingUci()
        mode = DsaBridgeMode()
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
        )
        mode.configure_interface(uci, net)

        cmds = " ".join(uci.commands)
        self.assertIn("br-lan.1", cmds)
        self.assertIn("192.168.1.1", cmds)


# ================================================================
# Swconfig 桥接模式测试
# ================================================================
class TestSwconfigBridgeMode(unittest.TestCase):
    """Swconfig 模式的配置生成"""

    def _make_switch(self, lan_ports=None):
        return SwitchInfo(
            name="switch0",
            cpu_port=5,
            cpu_interface="eth0",
            lan_ports=lan_ports or [1, 2, 3],
            wan_port=0,
        )

    def _make_hw(self, lan_ports=None):
        sw = self._make_switch(lan_ports)
        return HardwareInfo(
            mode="swconfig",
            wan_interface="eth0",
            lan_ports=[],
            switch=sw,
        )

    def test_configure_base_creates_switch_and_wan_vlan(self):
        """configure_base 应创建 switch 和 WAN VLAN 2"""
        uci = RecordingUci()
        hw = self._make_hw()
        mode = SwconfigBridgeMode(hw.switch)
        mode.configure_base(uci, hw)

        cmds = " ".join(uci.commands)
        self.assertIn("switch0", cmds)
        self.assertIn("enable_vlan", cmds)
        # WAN VLAN 2 保护
        self.assertIn("vlan='2'", cmds)
        self.assertIn("0 5t", cmds)

    def test_configure_vlan_with_user_ports(self):
        """configure_vlan 用户指定端口"""
        uci = RecordingUci()
        hw = self._make_hw()
        mode = SwconfigBridgeMode(hw.switch)
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
            ports=["lan1", "lan2"],
        )
        mode.configure_vlan(uci, net, hw)

        cmds = " ".join(uci.commands)
        self.assertIn("1 2 5t", cmds)

    def test_configure_vlan_default_vlan1_all_ports(self):
        """configure_vlan VLAN 1 默认使用所有 LAN 口"""
        uci = RecordingUci()
        hw = self._make_hw()
        mode = SwconfigBridgeMode(hw.switch)
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
        )
        mode.configure_vlan(uci, net, hw)

        cmds = " ".join(uci.commands)
        self.assertIn("1 2 3 5t", cmds)

    def test_configure_vlan_non_default_cpu_only(self):
        """configure_vlan 非 VLAN 1 且无端口 → 仅 CPU"""
        uci = RecordingUci()
        hw = self._make_hw()
        mode = SwconfigBridgeMode(hw.switch)
        net = NetworkConfig(
            name="iot", vlan_id=3, role="isolate",
            subnet="192.168.3.1", netmask="255.255.255.0",
        )
        mode.configure_vlan(uci, net, hw)

        cmds = " ".join(uci.commands)
        # 应仅有 CPU tagged
        self.assertIn("5t", cmds)

    def test_configure_interface_uses_ethX_vid(self):
        """configure_interface 应使用 eth0.VID"""
        uci = RecordingUci()
        hw = self._make_hw()
        mode = SwconfigBridgeMode(hw.switch)
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
        )
        mode.configure_interface(uci, net)

        cmds = " ".join(uci.commands)
        self.assertIn("eth0.1", cmds)
        self.assertIn("bridge", cmds)


# ================================================================
# 工厂函数测试
# ================================================================
class TestCreateBridgeMode(unittest.TestCase):
    """create_bridge_mode 工厂函数"""

    def test_swconfig_hw_returns_swconfig_mode(self):
        sw = SwitchInfo(name="switch0", cpu_port=5, cpu_interface="eth0",
                        lan_ports=[1, 2, 3], wan_port=0)
        hw = HardwareInfo(mode="swconfig", wan_interface="eth0",
                          lan_ports=[], switch=sw)
        mode = create_bridge_mode(hw)
        self.assertEqual(mode.mode_name, "Swconfig")

    def test_dsa_hw_returns_dsa_mode(self):
        hw = HardwareInfo(mode="dsa", wan_interface="eth0",
                          lan_ports=["eth1", "eth2"])
        mode = create_bridge_mode(hw)
        self.assertEqual(mode.mode_name, "DSA")


if __name__ == "__main__":
    unittest.main()
