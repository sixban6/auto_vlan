"""
配置器层 — 每个类负责一个 UCI 子系统。

遵循单一职责原则：DHCP、WiFi、Firewall 各司其职。
桥接/接口配置已迁移至 bridge_modes.py（BridgeMode 策略）。
角色相关的差异化逻辑委托给 NetworkRole 策略对象处理。
"""

from __future__ import annotations

import secrets
import string
from typing import Optional

from models import NetworkConfig, ProxyConfig, WifiInfo
from roles import NetworkRole
from uci import UciExecutor


# ================================================================
# DHCP 配置器
# ================================================================
class DhcpConfigurator:
    """
    配置 DHCP 服务。

    通用参数在此设置，角色特有的 DHCP Option 委托给 NetworkRole 处理。
    """

    def configure(
        self,
        uci: UciExecutor,
        net: NetworkConfig,
        proxy_cfg: Optional[ProxyConfig],
        role: NetworkRole,
    ) -> None:
        name = net.name
        print(f"  [DHCP] {name} — 基础配置")
        uci.set(f"dhcp.{name}", "dhcp")
        uci.set(f"dhcp.{name}.interface", name)
        uci.set(f"dhcp.{name}.start", "100")
        uci.set(f"dhcp.{name}.limit", "150")
        uci.set(f"dhcp.{name}.leasetime", "12h")

        # 委托角色策略处理差异化逻辑
        role.configure_dhcp(uci, net, proxy_cfg)


# ================================================================
# WiFi 配置器
# ================================================================
class WiFiConfigurator:
    """配置 WiFi AP 接口，支持密码自动生成"""

    DEFAULT_RADIO = "radio0"
    PASSWORD_LENGTH = 8

    def configure(
        self, uci: UciExecutor, net: NetworkConfig, radio: str | None = None
    ) -> WifiInfo | None:
        if net.wifi is None:
            return None

        # 检查 wireless 子系统是否可用（x86 Docker 等环境可能没有无线硬件）
        # Export 模式下跳过检查，假设目标设备有无线能力
        if not uci.is_export and not uci.is_dry_run and uci.query("show wireless") is None:
            print(f"  [WiFi] ⚠️  无线子系统不可用，跳过 WiFi 配置: {net.wifi.ssid}")
            return None

        ssid = net.wifi.ssid
        password = net.wifi.password
        if password == "auto_generate":
            password = self._generate_password()

        device = radio or self.DEFAULT_RADIO
        print(f"  [WiFi] SSID: {ssid} @ {device}")

        uci.add("wireless", "wifi-iface")
        uci.set("wireless.@wifi-iface[-1].device", device)
        uci.set("wireless.@wifi-iface[-1].mode", "ap")
        uci.set("wireless.@wifi-iface[-1].ssid", ssid)
        uci.set("wireless.@wifi-iface[-1].encryption", "psk2")
        uci.set("wireless.@wifi-iface[-1].key", password)
        uci.set("wireless.@wifi-iface[-1].network", net.name)

        return WifiInfo(ssid=ssid, password=password, role=net.role)

    @staticmethod
    def _generate_password(length: int = 8) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(secrets.choice(chars) for _ in range(length))


# ================================================================
# Firewall 配置器
# ================================================================
class FirewallConfigurator:
    """
    配置防火墙安全区域。

    默认策略：forward=REJECT（最小权限原则）
    角色特有的转发规则委托给 NetworkRole 处理。
    """

    def configure(
        self, uci: UciExecutor, net: NetworkConfig, role: NetworkRole
    ) -> None:
        zone = net.name
        print(f"  [Firewall] 区域: {zone} (角色: {net.role})")

        # 基础区域 — 安全基线: 默认拒绝转发
        uci.set(f"firewall.{zone}", "zone")
        uci.set(f"firewall.{zone}.name", zone)
        uci.set(f"firewall.{zone}.network", net.name)
        uci.set(f"firewall.{zone}.input", "ACCEPT")
        uci.set(f"firewall.{zone}.output", "ACCEPT")
        uci.set(f"firewall.{zone}.forward", "REJECT")
        uci.set(f"firewall.{zone}.masq", "1")

        # 所有区域都需要访问 WAN
        uci.add("firewall", "forwarding")
        uci.set("firewall.@forwarding[-1].src", zone)
        uci.set("firewall.@forwarding[-1].dest", "wan")

        # 委托角色策略处理额外规则
        role.configure_firewall(uci, zone, net)
