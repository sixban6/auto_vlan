"""
hw_detect 模块测试 — 覆盖 DSA / Swconfig 各种场景。
"""

import subprocess
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# 让 import 能找到项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hw_detect import (
    HardwareInfo,
    SwitchInfo,
    detect_hardware,
    _detect_swconfig,
    _detect_dsa,
    _detect_swconfig_ports_from_cli,
)
from uci import UciExecutor


# ================================================================
# 辅助：创建一个可编程的 MockUci
# ================================================================
class MockUci(UciExecutor):
    """可编程的 UCI 查询模拟器"""

    def __init__(self, responses: dict[str, str | None] = None):
        super().__init__()
        self._responses = responses or {}

    def query(self, command: str) -> str | None:
        # 精确匹配
        if command in self._responses:
            return self._responses[command]
        # 模糊匹配 (grep 类)
        for key, val in self._responses.items():
            if key in command:
                return val
        return None


# ================================================================
# Swconfig 探测测试
# ================================================================
class TestSwconfigDetection(unittest.TestCase):
    """Swconfig 模式下的硬件探测"""

    def _make_uci(self, vlan0_ports="1 2 3 5t", vlan1_ports="0 5t",
                  switch_name="switch0", wan_ifname="eth0.2",
                  lan_ifname="eth0.1") -> MockUci:
        return MockUci({
            "show network | grep '=switch'": "network.switch0=switch",
            "show network | grep '=bridge-vlan'": None,
            "get network.@switch[0].name": switch_name,
            "get network.wan.ifname": wan_ifname,
            f"show network | grep 'switch_vlan.*ports='":
                f"network.@switch_vlan[0].ports='{vlan0_ports}'\n"
                f"network.@switch_vlan[1].ports='{vlan1_ports}'",
            "get network.@switch_vlan[1].ports": vlan1_ports,
            "get network.lan.ifname": lan_ifname,
        })

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[])
    def test_basic_3_lan_ports(self, _mock_cli):
        """3 个 LAN 口 (1,2,3)，WAN=0，CPU=5"""
        uci = self._make_uci(vlan0_ports="1 2 3 5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        self.assertEqual(hw.mode, "swconfig")
        self.assertIsNotNone(hw.switch)
        self.assertEqual(hw.switch.lan_ports, [1, 2, 3])
        self.assertEqual(hw.switch.wan_port, 0)
        self.assertEqual(hw.switch.cpu_port, 5)

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[])
    def test_unsorted_lan_ports_get_sorted(self, _mock_cli):
        """UCI 中端口顺序乱序 (3,1,2) → 输出应排序为 [1,2,3]"""
        uci = self._make_uci(vlan0_ports="3 1 2 5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        self.assertEqual(hw.switch.lan_ports, [1, 2, 3])

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[])
    def test_ghost_port_excluded_when_uci_has_multiple(self, _mock_cli):
        """UCI 有 3 个端口 → 不调用 CLI → ghost port 不会混入"""
        uci = self._make_uci(vlan0_ports="1 2 3 5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        # CLI 不应被调用 (因 UCI 已有 >=2 个端口)
        _mock_cli.assert_not_called()
        self.assertEqual(hw.switch.lan_ports, [1, 2, 3])

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[0, 1, 2, 3, 4, 5])
    def test_cli_fallback_when_only_one_lan_port(self, _mock_cli):
        """UCI 只配了 1 个 LAN 口 → 回退到 CLI 探测"""
        uci = self._make_uci(vlan0_ports="1 5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        # CLI 应该被调用 (因 UCI 只有 1 个端口)
        _mock_cli.assert_called_once()
        # CLI 返回 [0..5], 排除 CPU=5 和 WAN=0 → [1,2,3,4]
        self.assertEqual(hw.switch.lan_ports, [1, 2, 3, 4])

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[0, 1, 2, 3, 4, 5])
    def test_cli_fallback_when_zero_lan_ports(self, _mock_cli):
        """UCI 一个 LAN 口都没有 (极端情况) → 回退到 CLI"""
        uci = self._make_uci(vlan0_ports="5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        _mock_cli.assert_called_once()
        self.assertEqual(hw.switch.lan_ports, [1, 2, 3, 4])

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[])
    def test_wan_port_removed_from_lan(self, _mock_cli):
        """WAN 口不应出现在 LAN 列表中"""
        # 模拟 UCI 将 port 0 同时放在 VLAN 1 和 VLAN 2
        uci = self._make_uci(vlan0_ports="0 1 2 3 5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        self.assertNotIn(0, hw.switch.lan_ports)
        self.assertEqual(hw.switch.wan_port, 0)
        self.assertEqual(hw.switch.lan_ports, [1, 2, 3])

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[])
    def test_cpu_port_detection(self, _mock_cli):
        """CPU 端口 (带 t 后缀) 应被正确解析"""
        # CPU 在端口 0 的情况 (某些 AR71xx 路由器)
        uci = self._make_uci(vlan0_ports="2 3 4 0t", vlan1_ports="1 0t")
        hw = detect_hardware(uci)

        self.assertEqual(hw.switch.cpu_port, 0)
        self.assertEqual(hw.switch.wan_port, 1)
        self.assertNotIn(0, hw.switch.lan_ports)

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[])
    def test_4_lan_ports(self, _mock_cli):
        """标准 5 口路由器 (WAN=0, LAN=1,2,3,4, CPU=5)"""
        uci = self._make_uci(vlan0_ports="1 2 3 4 5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        self.assertEqual(hw.switch.lan_ports, [1, 2, 3, 4])
        self.assertEqual(hw.switch.wan_port, 0)

    @patch("hw_detect._detect_swconfig_ports_from_cli", return_value=[])
    def test_single_lan_port_default_fallback(self, _mock_cli):
        """CLI 也没数据时，单 LAN 口应保留"""
        uci = self._make_uci(vlan0_ports="1 5t", vlan1_ports="0 5t")
        hw = detect_hardware(uci)

        # CLI 返回空 → lan_ports 保持 UCI 的 [1]
        self.assertEqual(hw.switch.lan_ports, [1])


# ================================================================
# DSA 探测测试
# ================================================================
class TestDsaDetection(unittest.TestCase):
    """DSA 模式下的硬件探测"""

    def _make_uci(self, wan_device="eth0", lan_ports_str="eth1 eth2 eth3") -> MockUci:
        return MockUci({
            "show network | grep '=switch'": None,
            "show network | grep '=bridge-vlan'": "network.cfg0=bridge-vlan",
            "get network.wan.device": wan_device,
            "get network.wan.ifname": None,
            "get network.@device[0].ports": lan_ports_str,
        })

    def test_basic_dsa_3_ports(self):
        """DSA 基础: 3 个 LAN 口"""
        uci = self._make_uci(lan_ports_str="eth1 eth2 eth3")
        hw = detect_hardware(uci)

        self.assertEqual(hw.mode, "dsa")
        self.assertEqual(hw.lan_ports, ["eth1", "eth2", "eth3"])
        self.assertEqual(hw.wan_interface, "eth0")

    def test_dsa_ports_sorted(self):
        """DSA 端口应排序 (eth3 eth1 eth2 → eth1 eth2 eth3)"""
        uci = self._make_uci(lan_ports_str="eth3 eth1 eth2")
        hw = detect_hardware(uci)

        self.assertEqual(hw.lan_ports, ["eth1", "eth2", "eth3"])

    def test_dsa_lan_named_ports(self):
        """DSA 使用 lan1/lan2/lan3 命名的端口"""
        uci = self._make_uci(lan_ports_str="lan1 lan2 lan3", wan_device="wan")
        hw = detect_hardware(uci)

        self.assertEqual(hw.lan_ports, ["lan1", "lan2", "lan3"])
        self.assertEqual(hw.wan_interface, "wan")

    def test_dsa_fallback_ports(self):
        """DSA 无法获取端口时使用默认值"""
        uci = MockUci({
            "show network | grep '=switch'": None,
            "show network | grep '=bridge-vlan'": "network.cfg0=bridge-vlan",
            "get network.wan.device": "eth0",
            "get network.wan.ifname": None,
            "get network.@device[0].ports": None,
            "get network.lan_dev.ports": None,
        })
        hw = detect_hardware(uci)

        self.assertEqual(hw.lan_ports, ["eth1", "eth2"])

    def test_dsa_no_switch_no_bridge_defaults_to_dsa(self):
        """无 switch 也无 bridge-vlan 配置 → 默认 DSA"""
        uci = MockUci({
            "show network | grep '=switch'": None,
            "show network | grep '=bridge-vlan'": None,
            "get network.wan.device": "eth0",
            "get network.wan.ifname": None,
            "get network.@device[0].ports": "eth1 eth2",
        })
        hw = detect_hardware(uci)

        self.assertEqual(hw.mode, "dsa")


# ================================================================
# Export 模式测试
# ================================================================
class TestExportMode(unittest.TestCase):
    """Export 模式下应使用默认值"""

    def test_export_returns_dsa_defaults(self):
        uci = UciExecutor(export=True)
        hw = detect_hardware(uci)

        self.assertEqual(hw.mode, "dsa")
        self.assertEqual(hw.wan_interface, "eth0")
        self.assertEqual(hw.lan_ports, ["eth1", "eth2"])


# ================================================================
# CLI 探测函数测试
# ================================================================
class TestSwconfigCliProbe(unittest.TestCase):
    """swconfig CLI 调用的端口解析"""

    @patch("subprocess.run")
    def test_parse_port_output(self, mock_run):
        """解析 swconfig show 的标准输出"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Port 0:\n  ...\nPort 1:\n  ...\nPort 2:\n  ...\nPort 3:\n  ...\nPort 4:\n  ...\nPort 5:\n  ...\n"
        )
        uci = UciExecutor()  # 非 export
        ports = _detect_swconfig_ports_from_cli(uci, "switch0")
        self.assertEqual(ports, [0, 1, 2, 3, 4, 5])

    @patch("subprocess.run")
    def test_cli_failure_returns_empty(self, mock_run):
        """CLI 失败时返回空列表"""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        uci = UciExecutor()
        ports = _detect_swconfig_ports_from_cli(uci, "switch0")
        self.assertEqual(ports, [])

    def test_export_mode_skips_cli(self):
        """Export 模式下不调用 CLI"""
        uci = UciExecutor(export=True)
        ports = _detect_swconfig_ports_from_cli(uci, "switch0")
        self.assertEqual(ports, [])


if __name__ == "__main__":
    unittest.main()
