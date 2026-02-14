# 知识点：如何在 OpenWrt 中判断物理网口数量

在 OpenWrt 系统中，不同的内核版本和硬件架构使用了两套截然不同的网络驱动模型：**DSA (Distributed Switch Architecture)** 和 **Swconfig (Legacy Switch Configuration)**。这导致判断物理网口数量的方法也完全不同。

`hw_detect.py` 模块封装了这一逻辑，以下是具体实现原理。

## 1. 核心判断逻辑

为了兼容性，脚本采用以下优先级进行探测：

1.  **优先检查 Swconfig**: `show network | grep '=switch'`
    -   即便某些新设备支持 DSA，旧配置可能仍残留 Swconfig 格式。
2.  **其次检查 DSA**: `show network | grep '=bridge-vlan'`
    -   这是现代 OpenWrt (21.02+) 的标准配置方式。
3.  **默认回退 DSA**: 如果都无法明确判定，假设为现代 DSA 设备。

---

## 2. DSA 模式 (分布式交换架构)

DSA 将每个物理网口视为独立的网络接口 (如 `eth1`, `eth2`, `lan1`, `wan`)，不再依赖虚拟的 VLAN ID 来区分端口。

### 如何判断物理网口？

DSA 模式下，物理网口通常直接作为 `br-lan` 网桥的成员接口存在。

**步骤：**

1.  **获取 `br-lan` 的成员列表**:
    -   命令：`uci get network.@device[0].ports` (通常 br-lan 是第一个 device)
    -   备选：`uci get network.lan_dev.ports` (如果使用了具名 device 配置)
    -   输出示例：`eth1 eth2 eth3`

2.  **解析端口列表**:
    -   直接分割字符串，每个元素即为一个物理网口。
    -   例如 `['eth1', 'eth2', 'eth3']` -> 3 个 LAN 口。

3.  **WAN 口识别**:
    -   命令：`uci get network.wan.device` 或 `uci get network.wan.ifname`
    -   通常 WAN 口独立于 bridge 之外 (例如 `eth0`)。

**总结 (DSA)**:
-   **物理网口总数** = `len(br-lan.ports) + 1 (WAN)`
-   **接口名**：即为 Linux 网络接口名 (`ethX`, `lanX`)。

---

## 3. Swconfig 模式 (传统交换芯片配置)

Swconfig 模式下，所有物理网口在操作系统层面只看到一个 `eth0` (CPU 接口)，通过 switch 芯片内部的 VLAN tag 来区分流量来源。物理网口对 OS 不可见。

### 如何判断物理网口？

由于 OS 看不到物理口，我们需要查询 switch 芯片的配置或状态。

**方法 A: 解析 UCI 配置 (静态)**

1.  **定位 Switch**: `uci get network.@switch[0].name` (通常为 `switch0`)。
2.  **识别 CPU 端口**:
    -   扫描 `switch_vlan` 配置，找到带有 `t` (tagged) 标记的端口号。
    -   例如 `ports='0t 2 3'`，其中 `0t` 是 CPU 口 (连接 eth0)。
3.  **识别 LAN 端口**:
    -   在 `switch_vlan` (通常 vlan 1) 中，**去掉** CPU 端口和可能的 WAN 端口。
    -   剩余的数字即为 LAN 物理端口号。
4.  **识别 WAN 端口**:
    -   通常在另一个 `switch_vlan` (通常 vlan 2) 中。或者根据 `network.wan.ifname=eth0.2` 推断 VLAN 2 是 WAN。

**方法 B: 使用 `swconfig` 命令 (动态/更准确)**

有时候 UCI 配置不完整 (例如只配置了一个 LAN 口)，但硬件实际上有 5 个口。`swconfig` 工具可以直接询问驱动。

**步骤：**

1.  **列出所有端口**:
    -   命令：`swconfig dev switch0 show`
    -   输出会包含 `Port 0: ...`, `Port 1: ...` 等信息。
2.  **解析输出**:
    -   遍历输出行，提取所有 `Port X`。
3.  **排除 CPU 和 WAN**:
    -   根据 UCI 配置已知的 CPU 口 (如 0) 和 WAN 口 (如 1) 进行排除。
    -   剩余的就是可用的 LAN 物理端口。

**总结 (Swconfig)**:
-   **物理网口** = 交换芯片端口号 (0, 1, 2, 3, 4...)
-   需要结合 CPU 口连接位置 (`eth0`) 和 VLAN 配置来推断每个物理口的用途。
