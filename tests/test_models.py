"""
models.py 测试 — YAML 解析、默认值推导、兼容性。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import parse_config, NetworkConfig, WifiConfig, ProxyConfig


class TestParseConfig(unittest.TestCase):
    """parse_config 工厂函数测试"""

    def test_basic_parsing(self):
        """基本: 一个带 WiFi 的网络"""
        raw = {
            "proxy": {"side_router_ip": "192.168.1.2"},
            "networks": [{
                "name": "lan",
                "vlan_id": 1,
                "role": "proxy",
                "wifi": {"ssid": "MyWifi", "password": "12345678"},
            }],
        }
        proxy, networks = parse_config(raw)

        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.side_router_ip, "192.168.1.2")
        self.assertEqual(proxy.proxy_dhcp_mode, "main")
        self.assertEqual(len(networks), 1)

        net = networks[0]
        self.assertEqual(net.name, "lan")
        self.assertEqual(net.vlan_id, 1)
        self.assertEqual(net.role, "proxy")
        self.assertIsNotNone(net.wifi)
        self.assertEqual(net.wifi.ssid, "MyWifi")
        self.assertEqual(net.wifi.password, "12345678")

    def test_subnet_auto_derived_from_vlan(self):
        """subnet 默认从 vlan_id 推导: 192.168.{vlan_id}.1"""
        raw = {
            "networks": [{
                "name": "iot",
                "vlan_id": 3,
                "role": "isolate",
            }],
        }
        _, networks = parse_config(raw)
        self.assertEqual(networks[0].subnet, "192.168.3.1")

    def test_custom_subnet_override(self):
        """用户自定义 subnet 应覆盖自动推导"""
        raw = {
            "networks": [{
                "name": "iot",
                "vlan_id": 3,
                "role": "isolate",
                "subnet": "10.0.0.1",
            }],
        }
        _, networks = parse_config(raw)
        self.assertEqual(networks[0].subnet, "10.0.0.1")

    def test_default_netmask(self):
        """默认 netmask 应为 255.255.255.0"""
        raw = {"networks": [{"name": "x", "vlan_id": 1, "role": "clean"}]}
        _, networks = parse_config(raw)
        self.assertEqual(networks[0].netmask, "255.255.255.0")

    def test_wifi_auto_password(self):
        """未指定 password 时应使用 'auto_generate'"""
        raw = {
            "networks": [{
                "name": "lan",
                "vlan_id": 1,
                "role": "proxy",
                "wifi": {"ssid": "Test"},
            }],
        }
        _, networks = parse_config(raw)
        self.assertEqual(networks[0].wifi.password, "auto_generate")

    def test_no_wifi(self):
        """无 WiFi 的网络: wifi 字段应为 None"""
        raw = {"networks": [{"name": "x", "vlan_id": 1, "role": "clean"}]}
        _, networks = parse_config(raw)
        self.assertIsNone(networks[0].wifi)

    def test_no_proxy(self):
        """无 proxy 配置时返回 None"""
        raw = {"networks": [{"name": "x", "vlan_id": 1, "role": "clean"}]}
        proxy, _ = parse_config(raw)
        self.assertIsNone(proxy)

    def test_legacy_global_format(self):
        """兼容旧 global 配置格式"""
        raw = {
            "global": {"side_router_ip": "10.0.0.1"},
            "networks": [{"name": "x", "vlan_id": 1, "role": "clean"}],
        }
        proxy, _ = parse_config(raw)
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.side_router_ip, "10.0.0.1")

    def test_alias_defaults_to_name(self):
        """alias 默认等于 name"""
        raw = {"networks": [{"name": "lan", "vlan_id": 1, "role": "proxy"}]}
        _, networks = parse_config(raw)
        self.assertEqual(networks[0].alias, "lan")

    def test_custom_alias(self):
        """自定义 alias"""
        raw = {"networks": [{"name": "lan", "vlan_id": 1, "role": "proxy", "alias": "Main LAN"}]}
        _, networks = parse_config(raw)
        self.assertEqual(networks[0].alias, "Main LAN")

    def test_ports_field(self):
        """用户手动指定 ports"""
        raw = {"networks": [{"name": "lan", "vlan_id": 1, "role": "proxy", "ports": ["lan1", "lan2"]}]}
        _, networks = parse_config(raw)
        self.assertEqual(networks[0].ports, ["lan1", "lan2"])

    def test_multiple_networks(self):
        """多网络解析"""
        raw = {
            "networks": [
                {"name": "lan", "vlan_id": 1, "role": "proxy"},
                {"name": "home", "vlan_id": 5, "role": "clean"},
                {"name": "iot", "vlan_id": 3, "role": "isolate"},
            ],
        }
        _, networks = parse_config(raw)
        self.assertEqual(len(networks), 3)
        self.assertEqual([n.name for n in networks], ["lan", "home", "iot"])
        self.assertEqual([n.vlan_id for n in networks], [1, 5, 3])

    def test_empty_networks(self):
        """空 networks 列表"""
        raw = {"networks": []}
        _, networks = parse_config(raw)
        self.assertEqual(len(networks), 0)


if __name__ == "__main__":
    unittest.main()
