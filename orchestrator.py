"""
编排器 — 顶层流水线，串联所有配置器完成端到端配置。

职责：加载 YAML → 解析模型 → 探测硬件 → 创建桥接模式 → 遍历网络 → 调用配置器 → 提交 → 输出摘要。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from bridge_modes import BridgeMode, create_bridge_mode
from configurators import (
    DhcpConfigurator,
    FirewallConfigurator,
    WiFiConfigurator,
)
from hw_detect import HardwareInfo, detect_hardware
from models import WifiInfo, parse_config
from roles import RoleRegistry
from uci import UciExecutor


class NetworkOrchestrator:
    """
    网络配置编排器。

    使用示例：
        uci = UciExecutor(dry_run=True)
        registry = create_default_registry()
        orchestrator = NetworkOrchestrator(uci, registry)
        orchestrator.run("network_plan.yaml")
    """

    def __init__(self, uci: UciExecutor, registry: RoleRegistry) -> None:
        self._uci = uci
        self._registry = registry

        # 配置器实例
        self._dhcp = DhcpConfigurator()
        self._wifi = WiFiConfigurator()
        self._firewall = FirewallConfigurator()

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------
    def run(self, config_path: str) -> None:
        """执行完整的网络配置流程"""
        proxy_cfg, networks = self._load_config(config_path)
        wifi_table: list[WifiInfo] = []

        # 自动探测硬件
        hw = detect_hardware(self._uci)

        # 创建桥接模式
        bridge_mode = create_bridge_mode(hw)

        print("=" * 55)
        print(">>> 开始根据 YAML 配置网络")
        print(f"    桥接模式: {bridge_mode.mode_name} (自动探测)")
        print(f"    可用角色: {self._registry.available_roles}")
        print("=" * 55)

        # 1. 配置桥接基础设施（网桥或交换芯片）
        bridge_mode.configure_base(self._uci, hw)

        # 2. 逐网络配置
        for net in networks:
            role = self._registry.get(net.role)
            print(f"\n>>> 处理网络: {net.name} [{net.alias}] "
                  f"(VLAN {net.vlan_id}, 角色: {net.role})")

            bridge_mode.configure_vlan(self._uci, net, hw)
            bridge_mode.configure_interface(self._uci, net)
            self._dhcp.configure(self._uci, net, proxy_cfg, role)

            wifi_info = self._wifi.configure(self._uci, net)
            if wifi_info:
                wifi_table.append(wifi_info)

            self._firewall.configure(self._uci, net, role)

        # 3. 提交所有更改
        self._commit()

        # 4. 输出摘要
        self._print_summary(wifi_table)

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------
    @staticmethod
    def _load_config(config_path: str):
        """加载并解析 YAML 配置文件"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        return parse_config(raw)

    def _commit(self) -> None:
        """提交所有 UCI 子系统（跳过不存在的子系统）"""
        print("\n>>> 正在提交 UCI 配置...")
        for subsystem in ("network", "dhcp", "firewall", "wireless"):
            # Export 模式下无法探测目标环境，默认全部生成
            if self._uci.is_export:
                self._uci.commit(subsystem)
                continue

            # 运行时探测：某些环境可能缺少子系统（如 x86 Docker 无 wireless）
            if not self._uci.is_dry_run and self._uci.query(f"show {subsystem}") is None:
                print(f"  ⚠️  跳过 {subsystem}（子系统不存在）")
                continue
            self._uci.commit(subsystem)

    @staticmethod
    def _print_summary(wifi_table: list[WifiInfo]) -> None:
        """打印 WiFi 凭据摘要表"""
        print()
        print("=" * 55)
        print(" 配置完成！请重启网络服务或重启路由器。")
        print(" WiFi 信息如下（请截图保存）:")
        print("=" * 55)
        print(f"  {'SSID':<20} | {'Password':<15} | {'Role':<10}")
        print("  " + "-" * 50)
        for info in wifi_table:
            print(f"  {info.ssid:<20} | {info.password:<15} | {info.role:<10}")
        print("=" * 55)
