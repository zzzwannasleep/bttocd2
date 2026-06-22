# bt2cd2 — BT RSS 自动离线到 CloudDrive2

抓取 BT 站点（动漫花园 dmhy、BtHome/1lou、Nyaa 等）的 RSS，提取磁力 / 种子链接，
自动调用 **CloudDrive2 的离线下载**（`AddOfflineFiles`）转存到网盘。带一个简单的网页用于
管理 RSS 订阅源，内置防风控与反 Cloudflare 机制，并对管理后台做了登录鉴权。

## 功能

- 🕸️ **RSS 抓取**：支持 dmhy / BtHome(1lou) / Nyaa / 通用 torrent feed，自动解析 magnet 与 `.torrent`
- ☁️ **CD2 离线**：调用 CloudDrive2 gRPC `AddOfflineFiles`，落地到指定网盘文件夹
- 🖥️ **网页管理**：增删改查订阅源、立即检查、预览、推送历史
- 🧹 **去重**：按 GUID + infohash 去重，已转存的不会重复推送
- 🛡️ **防风控**：同站请求最小间隔 + 随机抖动、UA 轮换、顺序抓取、错误自动退避冷却
- 🌩️ **反 Cloudflare**：内置 `cloudscraper`；硬盾可挂 `FlareSolverr`；支持出站代理
- 🔐 **安全**：后台登录（PBKDF2 + 签名会话 Cookie、登录失败限速）、容器非 root、密钥/密码不入库不入镜像

## 快速开始

```bash
cd bttocd2
cp .env.example .env
# 编辑 .env：填 CD2_URL / CD2_USERNAME / CD2_PASSWORD，建议设置 WEB_PASSWORD
docker compose up -d --build
docker compose logs -f bt2cd2   # 若未设 WEB_PASSWORD，这里能看到自动生成的密码
```

打开 `http://<服务器IP>:8080`，用 `admin` + 密码登录。

> 容器访问宿主机上的 CD2：compose 已配置 `host.docker.internal`，`CD2_URL` 用
> `http://host.docker.internal:19798` 即可。CD2 在另一台机器就直接填它的地址。
> 若设置了 `CD2_*`，首次启动会自动创建一个名为 “CloudDrive2” 的默认分发目标。

## 分发目标（下载器 / 网盘）

本程序是「**解析 → 分发**」工具：解析源负责抓取磁力，**目标**负责接收。在网页
「分发目标」区可添加任意多个目标，每个解析源在「分发到」里选一个目标。

| 目标 | 说明 | 连接信息 | 位置字段 |
|------|------|----------|----------|
| **CloudDrive2** | 网盘离线（gRPC `AddOfflineFiles`） | 地址 / 账号 / 密码 | 网盘文件夹路径 |
| **qBittorrent** | BT 下载器（Web API v2） | Web UI 地址 / 账号 / 密码 / 分类 | 保存路径 savepath |
| **Transmission** | BT 下载器（RPC） | `…/transmission/rpc` 地址 / 账号 / 密码 | 下载目录 download-dir |

- 目标密码在接口返回时**自动打码**，编辑时留空表示不修改。
- 每个目标都能「**测试连接**」。源里的「目标位置」会覆盖目标默认位置，留空则用默认。
- 想加新下载器只需在 `app/targets/` 加一个子类并在 `__init__.py` 注册（接口见 `base.py`）。

## 添加订阅

网页右上「+ 新增订阅」，填写：

| 字段 | 说明 |
|------|------|
| 名称 | 备注名，如 `dmhy-动画` |
| RSS 地址 | 如 `https://share.dmhy.org/topics/rss/rss.xml` 或带关键词的搜索 RSS |
| 轮询间隔 | 分钟，最小 5（建议 ≥30 降低风控） |
| 目标文件夹 | CD2 路径，如 `/115网盘/离线下载` |
| 包含/排除 | 正则，按标题过滤，如包含 `1080p|简体`、排除 `720p` |

保存后可点「立即检查」或「预览（不推送）」验证规则是否正确。

## BT之家 1LOU（种子站）

1lou（现域名 `www.1lou.me`）**没有 RSS**，给的是 `.torrent` 种子而非磁力，而
CloudDrive2 自己也抓不到这种站点。所以本程序的处理方式是：

1. 抓取你填的**列表页**（如最新电影 `https://www.1lou.me/forum-1.htm`，或某个分类/搜索页）；
2. 进入每个新帖子，找到 `attach-download-<id>.htm` 种子附件；
3. **下载 `.torrent`**（附件无需登录），本地解析 bencode、算出 infohash，
   **转换成磁力链接**（`magnet:?xt=urn:btih:...&dn=...&tr=...`）；
4. 把磁力推给 CD2 离线下载。

新增源时类型选 **BT之家 1LOU**，「地址」填列表页 URL 即可。**附件无需登录**，
Cookie 框留空；只有个别受限板块才需要填 Cookie（或用 `ONELOU_COOKIE` 设全局默认）。

> 为降低风控，1lou 源建议间隔 ≥30 分钟；单次最多处理 `MAX_ITEMS_PER_RUN` 个新帖。

dmhy / Nyaa 这类**本身带 magnet 的 RSS** 直接填 RSS 地址即可。

## 关于风控与 Cloudflare

- **不要把间隔设太短**：同站最小间隔由 `HOST_MIN_INTERVAL`（默认 30s）+ `FETCH_JITTER_SECONDS`
  随机抖动控制；所有抓取**串行**执行，命中 403/429/503 会自动冷却退避。
- **普通 5 秒盾**：`cloudscraper` 通常可过。
- **硬盾（Turnstile / Managed Challenge）**：在 compose 中启用 `flaresolverr` 服务，
  并设置 `FLARESOLVERR_URL=http://flaresolverr:8191`。
- **换 IP**：设置 `CRAWL_PROXY` 走代理可进一步降低封禁概率。

## 刮削 · 元数据 · 重命名整理（追番）

参考 ani-rss，订阅可以挂上影视元数据并自动整理成 Emby/Jellyfin 目录结构。

- **刮削**：新增/编辑源时点「刮削」，按名字搜 **Bangumi**（免 Key，默认）或 **TMDB**
  （在「设置 → 元数据」填 API Key）。选中后自动填入标题/年份/海报/总集数；解析源在列表里
  以**海报卡片**展示。
- **季 / 集偏移**：`Season` 决定落到哪个季目录；`集数偏移`用于分割放送或跨季编号
  （如 RSS 里是 28 集、实际是第 2 季第 16 集，就填 `-12`）。
- **自动重命名整理**：打开开关后，每个剧集按解析到的集号落到
  `媒体库/标题 (年份)/Season NN/` 目录（命名模板可自定义，默认
  `{title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d}`）。
  弹窗里有实时命名预览。媒体库根目录在「设置」里设全局默认，单个订阅可覆盖。

> **当前实现**：在分发时把下载**落地目录**设为对应的 Emby/Jellyfin 季目录（对
> CloudDrive2 / qBittorrent / Transmission 都生效，非破坏性）。**文件名级**的
> `SxxEyy` 重命名（在下载器里改文件名）属于下一步，需要下载完成后回调各下载器的
> 文件接口，正在推进中。

## 自动构建镜像（GitHub Actions）

仓库内置 `.github/workflows/docker-build.yml`，push 到 `main` 或打 `v*` tag 时自动
构建多架构（amd64 / arm64）镜像。

- **GHCR（默认，免配置）**：用内置 `GITHUB_TOKEN` 推送到
  `ghcr.io/zzzwannasleep/bttocd2`，**无需任何 secret**。
  首次推送后到仓库 *Packages* 把该包设为 Public 即可公开拉取。
- **Docker Hub（可选）**：在仓库 *Settings → Secrets and variables → Actions* 添加：

  | Secret | 说明 |
  |--------|------|
  | `DOCKERHUB_USERNAME` | Docker Hub 用户名 |
  | `DOCKERHUB_TOKEN` | Docker Hub Access Token（在 Docker Hub *Account Settings → Security* 生成） |

  设置后会同时推送到 `docker.io/<用户名>/bttocd2`；不设则自动跳过这一步。

拉取并运行（把 compose 里的 `build: .` 换成镜像即可）：

```yaml
services:
  bt2cd2:
    image: ghcr.io/zzzwannasleep/bttocd2:latest
    # ...其余 environment / ports / volumes 同 docker-compose.yml
```

## 安全建议

- 生产务必设置强 `WEB_PASSWORD`；不要把 8080 直接暴露公网，建议放反代 + HTTPS。
- `.env` 与 `data/` 不要提交到仓库（已在 `.dockerignore`）。
- CD2 建议用**专用 API Token / 受限账号**，而非主账号密码。

## 架构

```
app/
  main.py             FastAPI：路由 + 登录鉴权 + 静态页
  config.py           环境变量配置
  security.py         密码哈希 + 签名会话 Cookie + 登录限速
  database.py/crud.py SQLite 存储（订阅、历史）
  fetcher.py          抓取：限速 + 抖动 + UA 轮换 + cloudscraper/FlareSolverr + 退避
  rss.py              RSS 解析 + magnet/种子/infohash 提取 + 正则过滤（dmhy/nyaa/通用）
  onelou.py           1lou 抓取：列表页→帖子→下载 .torrent→转磁力
  torrent.py          纯标准库 bencode 解析 + .torrent→magnet 转换
  targets/            可插拔分发目标：base / cd2 / qbittorrent / transmission
  scheduler.py        APScheduler：每分钟 tick，到期订阅串行处理
  static/             网页 UI
```

数据持久化在 `/data`（SQLite + 自动生成的密钥/密码）。

## 技术说明

- CD2 客户端基于 [`clouddrive`](https://pypi.org/project/clouddrive/) PyPI 包，封装在
  `clouddrive_client.py`，调用 `AddOfflineFiles({urls, toFolder, checkFolderAfterSecs})`。
  如上游包签名变动，只需改这一个文件。
- 抓取参考了 [waitfortea/BtHome](https://github.com/waitfortea/BtHome) 的反 Cloudflare 思路。

## 免责声明

仅供学习与个人合法用途。请遵守目标站点的 robots 与服务条款，合理设置抓取间隔，勿对站点造成压力。
