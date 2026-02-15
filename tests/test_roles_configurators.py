"""
roles.py + configurators.py 测试 — 角色注册表、DHCP/WiFi/防火墙配置器。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from roles import (
    RoleRegistry,
    ProxyRole,
    CleanRole,
    IsolateRole,
    create_default_registry,
)
from configurators import DhcpConfigurator, WiFiConfigurator, FirewallConfigurator
from models import NetworkConfig, ProxyConfig, WifiConfig
from uci import UciExecutor


class RecordingUci(UciExecutor):
    """记录所有 UCI 命令"""

    def __init__(self):
        super().__init__(dry_run=True)
        self.commands: list[str] = []

    def run(self, command: str) -> None:
        self.commands.append(f"uci {command}")


# ================================================================
# RoleRegistry 测试
# ================================================================
class TestRoleRegistry(unittest.TestCase):

    def test_register_and_get(self):
        registry = RoleRegistry()
        role = ProxyRole()
        registry.register("proxy", role)
        self.assertIs(registry.get("proxy"), role)

    def test_get_unknown_raises(self):
        registry = RoleRegistry()
        with self.assertRaises(ValueError) as ctx:
            registry.get("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_available_roles_sorted(self):
        registry = create_default_registry()
        roles = registry.available_roles
        self.assertEqual(roles, ["clean", "isolate", "proxy"])

    def test_default_registry_has_3_roles(self):
        registry = create_default_registry()
        for name in ("proxy", "clean", "isolate"):
            self.assertIsNotNone(registry.get(name))


# ================================================================
# ProxyRole 测试
# ================================================================
class TestProxyRole(unittest.TestCase):

    def _make_net(self, name="lan"):
        return NetworkConfig(
            name=name, vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
        )

    def test_proxy_main_mode_sets_gateway_dns(self):
        """Main 模式: 网关/DNS → 旁路由"""
        uci = RecordingUci()
        role = ProxyRole()
        proxy = ProxyConfig(side_router_ip="192.168.1.2", proxy_dhcp_mode="main")
        role.configure_dhcp(uci, self._make_net(), proxy)

        cmds = " ".join(uci.commands)
        self.assertIn("3,192.168.1.2", cmds)  # Gateway
        self.assertIn("6,192.168.1.2", cmds)  # DNS

    def test_proxy_side_mode_sets_ignore(self):
        """Side 模式: DHCP ignore"""
        uci = RecordingUci()
        role = ProxyRole()
        proxy = ProxyConfig(side_router_ip="192.168.1.2", proxy_dhcp_mode="side")
        role.configure_dhcp(uci, self._make_net(), proxy)

        cmds = " ".join(uci.commands)
        self.assertIn("ignore", cmds)

    def test_proxy_no_config_skips(self):
        """无 proxy 配置时不应崩溃"""
        uci = RecordingUci()
        role = ProxyRole()
        role.configure_dhcp(uci, self._make_net(), None)
        self.assertEqual(len(uci.commands), 0)


# ================================================================
# CleanRole 测试
# ================================================================
class TestCleanRole(unittest.TestCase):

    def test_clean_sets_public_dns(self):
        uci = RecordingUci()
        role = CleanRole()
        net = NetworkConfig(
            name="home", vlan_id=5, role="clean",
            subnet="192.168.5.1", netmask="255.255.255.0",
        )
        role.configure_dhcp(uci, net, None)

        cmds = " ".join(uci.commands)
        self.assertIn("223.5.5.5", cmds)


# ================================================================
# IsolateRole 测试
# ================================================================
class TestIsolateRole(unittest.TestCase):

    def test_isolate_sets_public_dns(self):
        uci = RecordingUci()
        role = IsolateRole()
        net = NetworkConfig(
            name="iot", vlan_id=3, role="isolate",
            subnet="192.168.3.1", netmask="255.255.255.0",
        )
        role.configure_dhcp(uci, net, None)

        cmds = " ".join(uci.commands)
        self.assertIn("223.5.5.5", cmds)


# ================================================================
# DhcpConfigurator 测试
# ================================================================
class TestDhcpConfigurator(unittest.TestCase):

    def test_basic_dhcp_setup(self):
        """应设置 start/limit/leasetime"""
        uci = RecordingUci()
        dhcp = DhcpConfigurator()
        role = CleanRole()
        net = NetworkConfig(
            name="lan", vlan_id=1, role="clean",
            subnet="192.168.1.1", netmask="255.255.255.0",
        )
        dhcp.configure(uci, net, None, role)

        cmds = " ".join(uci.commands)
        self.assertIn("dhcp.lan", cmds)
        self.assertIn("start", cmds)
        self.assertIn("limit", cmds)
        self.assertIn("leasetime", cmds)


# ================================================================
# WiFiConfigurator 测试
# ================================================================
class TestWiFiConfigurator(unittest.TestCase):

    def test_wifi_configured(self):
        """有 WiFi 配置时应生成 wifi-iface"""
        uci = RecordingUci()
        wifi_cfg = WiFiConfigurator()
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
            wifi=WifiConfig(ssid="TestSSID", password="12345678"),
        )
        info = wifi_cfg.configure(uci, net)

        self.assertIsNotNone(info)
        self.assertEqual(info.ssid, "TestSSID")
        self.assertEqual(info.password, "12345678")
        cmds = " ".join(uci.commands)
        self.assertIn("wifi-iface", cmds)
        self.assertIn("TestSSID", cmds)

    def test_no_wifi_returns_none(self):
        """无 WiFi 配置时应返回 None"""
        uci = RecordingUci()
        wifi_cfg = WiFiConfigurator()
        net = NetworkConfig(
            name="iot", vlan_id=3, role="isolate",
            subnet="192.168.3.1", netmask="255.255.255.0",
        )
        info = wifi_cfg.configure(uci, net)
        self.assertIsNone(info)

    def test_auto_generate_password(self):
        """auto_generate 应生成随机密码"""
        uci = RecordingUci()
        wifi_cfg = WiFiConfigurator()
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
            wifi=WifiConfig(ssid="Test", password="auto_generate"),
        )
        info = wifi_cfg.configure(uci, net)

        self.assertIsNotNone(info)
        self.assertNotEqual(info.password, "auto_generate")
        self.assertEqual(len(info.password), 8)

    def test_custom_radio(self):
        """指定 radio 参数"""
        uci = RecordingUci()
        wifi_cfg = WiFiConfigurator()
        net = NetworkConfig(
            name="lan", vlan_id=1, role="proxy",
            subnet="192.168.1.1", netmask="255.255.255.0",
            wifi=WifiConfig(ssid="Test", password="12345678"),
        )
        info = wifi_cfg.configure(uci, net, radio="radio1")

        cmds = " ".join(uci.commands)
        self.assertIn("radio1", cmds)


# ================================================================
# FirewallConfigurator 测试
# ================================================================
class TestFirewallConfigurator(unittest.TestCase):

    def test_firewall_zone_created(self):
        """应创建防火墙区域"""
        uci = RecordingUci()
        fw = FirewallConfigurator()
        role = CleanRole()
        net = NetworkConfig(
            name="iot", vlan_id=3, role="isolate",
            subnet="192.168.3.1", netmask="255.255.255.0",
        )
        fw.configure(uci, net, role)

        cmds = " ".join(uci.commands)
        self.assertIn("firewall.iot", cmds)
        self.assertIn("REJECT", cmds)  # forward=REJECT
        self.assertIn("forwarding", cmds)  # → WAN


if __name__ == "__main__":
    unittest.main()
