"""
数据模型层 — 纯数据类，无业务逻辑。
将 YAML 配置映射为类型安全的 Python 对象。

配置极简化：用户只需关注网络规划，硬件信息由运行时自动探测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ------------------------------------------------------------------
# WiFi 配置
# ------------------------------------------------------------------
@dataclass(frozen=True)
class WifiConfig:
    """单个 WiFi 接口的期望配置"""
    ssid: str
    password: str  # 原始值，可能是 "auto_generate"


# ------------------------------------------------------------------
# 网络（VLAN）配置
# ------------------------------------------------------------------
@dataclass(frozen=True)
class NetworkConfig:
    """单个 VLAN 网络的完整定义"""
    name: str
    vlan_id: int
    role: str       # "proxy" | "clean" | "isolate" | 用户自定义
    subnet: str     # 如 "192.168.1.1"
    netmask: str    # 如 "255.255.255.0"
    alias: str = ""
    wifi: Optional[WifiConfig] = None
    ports: list[str] = field(default_factory=list)  # 可选: 物理端口绑定 (lan1, lan2:t)


# ------------------------------------------------------------------
# 全局/代理 配置
# ------------------------------------------------------------------
@dataclass(frozen=True)
class ProxyConfig:
    """代理网络相关的全局参数"""
    side_router_ip: str        # 旁路由 IP
    proxy_dhcp_mode: str = "main"  # "main" | "side"


# ------------------------------------------------------------------
# WiFi 信息（输出用）
# ------------------------------------------------------------------
@dataclass
class WifiInfo:
    """运行结束后回显给用户的 WiFi 凭据"""
    ssid: str
    password: str
    role: str


# ------------------------------------------------------------------
# 工厂函数：从原始 dict 构建模型
# ------------------------------------------------------------------
def parse_config(raw: dict) -> tuple[Optional[ProxyConfig], list[NetworkConfig]]:
    """
    将 YAML 解析出的 dict 转换为强类型模型。

    极简配置示例:
        proxy:
            side_router_ip: "192.168.1.2"
        networks:
            - name: "lan"
            vlan_id: 1
            role: "proxy"
            wifi:
                ssid: "Youtube"
    """
    # --- proxy 配置 (可选) ---
    proxy_cfg = None
    if "proxy" in raw:
        p = raw["proxy"]
        proxy_cfg = ProxyConfig(
            side_router_ip=p["side_router_ip"],
            proxy_dhcp_mode=p.get("proxy_dhcp_mode", "main"),
        )

    # --- 兼容旧 global 配置格式 ---
    if proxy_cfg is None and "global" in raw:
        g = raw["global"]
        proxy_cfg = ProxyConfig(
            side_router_ip=g.get("side_router_ip", g.get("main_router_ip", "192.168.1.2")),
            proxy_dhcp_mode=g.get("proxy_dhcp_mode", "main"),
        )

    # --- 网络列表 ---
    networks: list[NetworkConfig] = []
    for entry in raw.get("networks", []):
        vlan_id = entry["vlan_id"]

        # 智能默认值
        subnet = entry.get("subnet", f"192.168.{vlan_id}.1")
        netmask = entry.get("netmask", "255.255.255.0")
        alias = entry.get("alias", entry["name"])
        ports = entry.get("ports", [])

        wifi = None
        if "wifi" in entry:
            w = entry["wifi"]
            wifi = WifiConfig(
                ssid=w["ssid"],
                password=w.get("password", "auto_generate"),
            )

        networks.append(
            NetworkConfig(
                name=entry["name"],
                vlan_id=vlan_id,
                role=entry["role"],
                subnet=subnet,
                netmask=netmask,
                alias=alias,
                wifi=wifi,
                ports=ports,
            )
        )

    return proxy_cfg, networks
