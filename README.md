# Auto VLAN — OpenWrt 网络自动化配置工具

一个基于 Python 的 OpenWrt 网络自动化工具。通过编辑一个 YAML 配置文件，即可自动完成 **VLAN 划分、DHCP 配置、WiFi 创建、防火墙隔离** 等全部操作。

支持 **DSA** 和 **Swconfig** 两种桥接模式，可自动检测路由器类型。

## ✨ 功能特性

- **声明式配置** — 只需编辑 `network_plan.yaml`，描述你想要的网络拓扑
- **双模式桥接** — 自动检测并适配 DSA（新款路由器）和 Swconfig（传统交换芯片路由器）
- **三种内置角色**：
  | 角色 | 用途 | 说明 |
  |------|------|------|
  | `proxy` | 翻墙网络 | DHCP 网关指向旁路由，流量走代理 |
  | `clean` | 纯净网络 | 直连 WAN，使用公共 DNS |
  | `isolate` | IoT 隔离网络 | 仅允许上外网，禁止访问内网 |
- **WiFi 密码自动生成** — 设为 `auto_generate` 即可随机生成安全密码
- **Dry-Run 模式** — 先预览所有 UCI 命令，确认无误再执行
- **OCP 架构** — 新增网络角色或桥接模式，无需修改已有代码

## 📋 前提条件

- OpenWrt 路由器（DSA 或 Swconfig 均可）
- Python 3.10+
- PyYAML（`pip install pyyaml`）

## 🚀 快速开始

### 1. 编辑配置文件

修改 `network_plan.yaml`，按需规划你的网络：

```yaml
# === OpenWrt 网络规划 ===
# 只需编辑此文件，然后运行 python3 setup_network.py
# 硬件信息（WAN/LAN/switch）由程序自动探测，无需手动配置

# 代理配置 (仅在需要旁路由翻墙时填写)
proxy:
  side_router_ip: "192.168.1.2"   # 旁路由 IP
  # proxy_dhcp_mode: "main"       # 可选: main(默认) / side

# 网络规划
# - subnet 默认从 vlan_id 推导: 192.168.{vlan_id}.1
# - netmask 默认: 255.255.255.0
# - wifi.password 不写则自动生成
networks:
  - name: "lan"
    vlan_id: 1
    role: "proxy"          # proxy=翻墙 | clean=纯净 | isolate=隔离
    wifi:
      ssid: "Youtube"

  - name: "home"
    vlan_id: 5
    role: "clean"
    wifi:
      ssid: "home"
      password: "12345678"

  - name: "iot"
    vlan_id: 3
    role: "isolate"
    subnet: "192.168.10.1"
    wifi:
      ssid: "IoT-Smart"
```

### 2. 试运行（推荐先执行）
```bash
opkg update
opkg install git-http
opkg install python3
opkg install python3-yaml
git clone https://github.com/sixban6/auto_vlan.git
cd auto_vlan
python3 setup_network.py --dry-run
```

该模式会打印所有将要执行的 `uci` 命令，但 **不会实际修改** 路由器配置。

### 3. 正式执行

```bash
python3 setup_network.py
```

执行完成后，脚本会输出所有 WiFi 的 SSID 和密码，**请截图保存**。

### 4. 指定桥接模式

默认自动检测，也可手动指定：

```bash
python3 setup_network.py --mode dsa        # 强制 DSA 模式
python3 setup_network.py --mode swconfig   # 强制 Swconfig 模式
python3 setup_network.py --mode auto       # 自动检测 (默认)
```

### 5. 指定配置文件

```bash
python3 setup_network.py --config /path/to/your_plan.yaml
```

## 🔀 桥接模式说明

| 模式 | 适用场景 | 原理 |
|------|----------|------|
| **DSA** | 较新的 OpenWrt (21.02+) | 使用 `br-lan` 网桥 + VLAN 过滤，接口绑定 `br-lan.VID` |
| **Swconfig** | 传统交换芯片路由器 | 使用 `switch0` + `switch_vlan`，接口绑定 `ethX.VID` |

**自动检测逻辑**：
1. 运行时：查询 `uci show network`，有 switch 配置 → Swconfig，否则 → DSA
2. Dry-run 时：YAML 中有 `switch` 配置 → Swconfig，否则 → DSA

## 📁 项目结构

```
auto_vlan/
├── setup_network.py   # CLI 入口
├── network_plan.yaml  # 用户配置文件（IaC）
├── models.py          # 数据模型（YAML → Python 对象）
├── bridge_modes.py    # 桥接模式策略（DSA / Swconfig + 自动检测）
├── configurators.py   # 配置器（DHCP / WiFi / Firewall）
├── roles.py           # 网络角色策略（proxy / clean / isolate）
├── orchestrator.py    # 编排器（串联所有配置器）
└── uci.py             # UCI 命令执行器（支持 dry-run）
```

## 🔧 自定义角色

如需新增网络角色（例如 `guest`），只需三步：

```python
# 1. 在 roles.py 中继承 NetworkRole
class GuestRole(NetworkRole):
    def configure_dhcp(self, uci, net, glob):
        # 你的 DHCP 逻辑
        pass

    def configure_firewall(self, uci, zone_name, net):
        # 你的防火墙逻辑
        pass

# 2. 在 create_default_registry() 中注册
registry.register("guest", GuestRole())

# 3. 在 YAML 中使用
#   role: "guest"
```

## ⚠️ 注意事项

- 该工具会**覆盖**路由器上已有的网络/DHCP/防火墙配置，请先备份
- 首次使用请务必通过 `--dry-run` 模式确认命令正确
- 执行后需要重启网络服务（`/etc/init.d/network restart`）或重启路由器

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。
