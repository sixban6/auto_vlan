"""
网络角色策略层 — OCP 的核心实现。

新增角色只需要：
  1. 继承 NetworkRole
  2. 实现 configure_dhcp() 和 configure_firewall()
  3. 在 RoleRegistry 中注册

无需修改任何已有代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from models import ProxyConfig, NetworkConfig
from uci import UciExecutor


# ================================================================
# 抽象基类
# ================================================================
class NetworkRole(ABC):
    """网络角色的策略接口"""

    @abstractmethod
    def configure_dhcp(
        self, uci: UciExecutor, net: NetworkConfig,
        proxy_cfg: Optional[ProxyConfig],
    ) -> None:
        """配置该角色特有的 DHCP 行为"""

    @abstractmethod
    def configure_firewall(
        self, uci: UciExecutor, zone_name: str, net: NetworkConfig
    ) -> None:
        """配置该角色特有的防火墙转发规则"""


# ================================================================
# 具体策略
# ================================================================
class ProxyRole(NetworkRole):
    """
    翻墙网络 — DHCP 网关指向旁路由，防火墙允许到 WAN 的转发。
    """

    def configure_dhcp(
        self, uci: UciExecutor, net: NetworkConfig,
        proxy_cfg: Optional[ProxyConfig],
    ) -> None:
        name = net.name
        if proxy_cfg is None:
            print(f"  [DHCP] Proxy 模式 — ⚠️ 未配置旁路由 IP，跳过网关指向")
            return

        if proxy_cfg.proxy_dhcp_mode == "main":
            # 主路由发 DHCP，但网关和 DNS 指向旁路由
            side_ip = proxy_cfg.side_router_ip
            print(f"  [DHCP] Proxy 模式 — 网关/DNS 指向旁路由: {side_ip}")
            uci.add_list(f"dhcp.{name}.dhcp_option", f"3,{side_ip}")  # Gateway
            uci.add_list(f"dhcp.{name}.dhcp_option", f"6,{side_ip}")  # DNS
            uci.set(f"dhcp.{name}.force", "1")
        else:
            # 旁路由接管 DHCP，主路由忽略
            print(f"  [DHCP] Proxy 模式 — 由旁路由接管 (本机 ignore)")
            uci.set(f"dhcp.{name}.ignore", "1")

    def configure_firewall(
        self, uci: UciExecutor, zone_name: str, net: NetworkConfig
    ) -> None:
        pass


class CleanRole(NetworkRole):
    """
    纯净网络 — 直连 WAN，使用公共 DNS，防火墙隔离。
    """

    # 推荐的公共 DNS
    PUBLIC_DNS = "223.5.5.5,114.114.114.114"

    def configure_dhcp(
        self, uci: UciExecutor, net: NetworkConfig,
        proxy_cfg: Optional[ProxyConfig],
    ) -> None:
        print(f"  [DHCP] Clean 模式 — 直连, DNS: {self.PUBLIC_DNS}")
        uci.add_list(f"dhcp.{net.name}.dhcp_option", f"6,{self.PUBLIC_DNS}")

    def configure_firewall(
        self, uci: UciExecutor, zone_name: str, net: NetworkConfig
    ) -> None:
        pass


class IsolateRole(NetworkRole):
    """
    隔离网络 — 仅允许上外网，完全隔离内网，使用公共 DNS。
    """

    PUBLIC_DNS = "223.5.5.5,114.114.114.114"

    def configure_dhcp(
        self, uci: UciExecutor, net: NetworkConfig,
        proxy_cfg: Optional[ProxyConfig],
    ) -> None:
        print(f"  [DHCP] Isolate 模式 — 隔离, DNS: {self.PUBLIC_DNS}")
        uci.add_list(f"dhcp.{net.name}.dhcp_option", f"6,{self.PUBLIC_DNS}")

    def configure_firewall(
        self, uci: UciExecutor, zone_name: str, net: NetworkConfig
    ) -> None:
        pass


# ================================================================
# 角色注册表 — 字符串 → 策略实例 的映射
# ================================================================
class RoleRegistry:
    """
    将 YAML 中的 role 字符串解析为对应的 NetworkRole 实例。

    使用方式：
        registry = RoleRegistry()
        registry.register("proxy", ProxyRole())
        role = registry.get("proxy")
    """

    def __init__(self) -> None:
        self._roles: dict[str, NetworkRole] = {}

    def register(self, name: str, role: NetworkRole) -> None:
        """注册一个角色策略"""
        self._roles[name] = role

    def get(self, name: str) -> NetworkRole:
        """根据名称获取角色策略，不存在则抛出明确异常"""
        if name not in self._roles:
            available = ", ".join(sorted(self._roles.keys()))
            raise ValueError(
                f"未知的网络角色 '{name}'，可用角色: [{available}]"
            )
        return self._roles[name]

    @property
    def available_roles(self) -> list[str]:
        return sorted(self._roles.keys())


# ================================================================
# 默认注册表工厂
# ================================================================
def create_default_registry() -> RoleRegistry:
    """创建包含所有内置角色的注册表"""
    registry = RoleRegistry()
    registry.register("proxy", ProxyRole())
    registry.register("clean", CleanRole())
    registry.register("isolate", IsolateRole())
    return registry
