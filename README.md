# K70 UniXNU — iOS 16.7.16 (20H392) bring-up

Redmi K70（vermeer，SM8550）上的 iOS 16.7.16 启动实验。启动链为
[UniXNU](https://unixnu.com/zh/concepts/boot-chain)：Android bootloader → BootShim → UEFI → UniXNU → DarwinBoot → XNU。

本仓库只保留**当前方案**（官方路线：独立 `unixnu` 分区 + ShengUfs 原生存储）。
旧方案（gap 内 3 GiB HFS 根 + mdev 窗口）已停用，历史保留在
`main-backup-20261120` 与 `k70/ufs-window-apfs` 分支。

## 状态摘要（2026-11-20）

| 项目 | 状态 |
| --- | --- |
| 分区 | 已改为 `userdata` 182.07 GiB + `unixnu` 32 GiB（sda29 / sda30），主备 GPT 校验通过 |
| Android | `_a` 正常启动，`/data` 加密挂载（F2FS, dm-default-key） |
| 内核 | XNU 8796.141.3 可构建、可启动；菜单已改名为 `iOS 16.7.16 (20H392)`，并带「重启到 Android」 |
| 存储驱动 | ShengUfs `af785c17` 已改为查找 `unixnu`（`wanted[]`），离线正反例通过 |
| 根镜像 | 官方 `build userdata` 产物构建中（OS raw 5.6 GiB + SystemOS 2.74 GiB，预计 8.38 GiB） |
| launchd | 旧方案曾用 HFS 根到达 launchd（PANIC SIGBUS 待解）；新方案尚未上机 |

## 分区现状（实测）

```
磁盘     253,306,601,472 B，逻辑扇区 4096
userdata sda29  5,716,032 .. 53,443,583   182.07 GiB
unixnu   sda30 53,443,584 .. 61,832,191    32.00 GiB
super           2,570,304 ..  5,716,031    12.00 GiB
```

主备 GPT 均逐字节回读校验；备份文件见 `work/gpt-before/`（本地）。

## 仓库结构

| 路径 | 作用 |
| --- | --- |
| `iphone16/` | 内核补丁与生成脚本：CPU/GIC、UFS 传输、诊断面板、`dw_origin_patch.py` |
| `rootchain/` | 启动链打包：`build.py`（trust / root / pack），生成 `unixnu.toml` 菜单 |
| `pinned-inputs/` | 固定输入清单（XNU 8796.141.3、ShengUfs、UEFI、core） |
| `tools/` | 辅助脚本（UFS 链接校验等） |
| `.github/workflows/k70-iphone16.yml` | 内核构建（macOS），含 unixnu 补丁与 legacy-iig 校验 |
| `.github/workflows/os-raw.yml` | 把 20H392 的 OS dmg 转成 raw（LZFSE → raw） |

## 固定输入

| 组件 | 版本 |
| --- | --- |
| XNU | 8796.141.3（对应 20H392） |
| iOS | 16.7.16，build 20H392，iPhone10,3 / iPhone10,6 |
| UniXNU core | `b6ae99c17194e6a18fd819d3148e69fe405e91fc` |
| ShengUfs | `af785c1777161a62931425c2faaa536ce0bebd5b`（已改为查找 `unixnu`） |
| legacy iig | Release `legacy-iig-driverkit-286`（`DriverKit-286`） |

`legacy-iig` 原先从一条已失效的 trycloudflare 隧道下载，现已挂到 Release：
归档 SHA-256 `9233305fd34b6ee7a6da2b3c35dac9e125ef0c7b2d32da54f63b4218d9f166d6`，
`iig` 与 `libclang.dylib` 哈希保持不变，CI 每次冷校验。

## 启动与部署

```
fastboot boot <boot.img>        # 不写任何分区
UEFI → UniXNU 菜单 → iOS 16.7.16 (20H392)
ShengUfs 读取 LUN0 GPT → 选中 unixnu → SHNGROOT 清单 → APFS 根卷 → launchd
```

部署根镜像时**只写 `unixnu`（sda30）**：

```
写前：/dev/block/by-name/unixnu → sda30，34,359,738,368 B，未挂载
写入：只写镜像实际长度，随后流式回读 SHA-256 对比
验收：SHNGROOT / 版本 1 / 两窗口 / header[4064:4096] == SHA256(header[:4064])
```

官方报告里的 `fastboot flash userdata` **不要执行**。

## 已知问题

1. **旧路线的 IOBSD 等待是死路**：面板 `RF K0 W1` 表示 `waitForMatchingService`
   进入后永不返回（30 秒超时也未触发）。新方案不再经过该路径。
2. **4 KiB 内核 / 16 KiB CodeDirectory**：签名页校验需要 `k70nosig` 规避；
   换分区不会解决该兼容问题。
3. **32 GiB 容量**：根镜像 8.38 GiB + 4 MiB guard + Data + 1 GiB 日志需装得下；
   首轮先不启用 Data 持久化与日志写入。

## 下一步

1. 生成并校验官方 `userdata-root.img`（32 GiB 目标）
2. 部署到 `unixnu` 并回读校验
3. `fastboot boot` 验证：选中 unixnu → APFS 根 UUID → launchd
4. 通过后再单独启用 iOS Data 持久化
5. 回 Android 确认 `/data` 仍正常

## 链接

- [UniXNU 文档](https://unixnu.com/zh/) · [移植指南](https://unixnu.com/zh/porting/)
- [Build guide](https://unixnu.com/zh/building)
- [设备仓库 UniXNU-vermeer](https://github.com/mansar1337/UniXNU-vermeer)
