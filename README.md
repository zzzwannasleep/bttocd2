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

## BT之家 1LOU（种子站，需登录 Cookie）

1lou（现域名 `www.1lou.me`）**没有 RSS**，且 `.torrent` 附件**需要登录**才能下载，
CloudDrive2 自己也无法抓取这种登录受限的种子。所以本程序的处理方式是：

1. 抓取你填的**列表页**（如最新电影 `https://www.1lou.me/forum-1.htm`，或某个分类/搜索页）；
2. 进入每个新帖子，找到 `attach-download-<id>.htm` 种子附件；
3. **用你的登录 Cookie 把 `.torrent` 下载下来**，本地解析 bencode、算出 infohash，
   **转换成磁力链接**（`magnet:?xt=urn:btih:...&dn=...&tr=...`）；
4. 把磁力推给 CD2 离线下载。

### 怎么填 Cookie

1. 浏览器登录 `www.1lou.me`；
2. F12 → Network，刷新页面，点任意请求 → Request Headers 里复制完整的 `Cookie:` 值；
3. 新增订阅时类型选 **BT之家 1LOU**，把 Cookie 粘到「Cookie」框（或用 `ONELOU_COOKIE` 设全局默认）。

> Cookie 会过期，过期后历史记录里会出现 `login/cookie expired` 类错误，重新复制一份即可。
> 为降低风控，1lou 订阅建议间隔 ≥30 分钟；单次最多处理 `MAX_ITEMS_PER_RUN` 个新帖。

dmhy / Nyaa 这类**本身带 magnet 的 RSS** 不需要 Cookie，直接填 RSS 地址即可。

## 关于风控与 Cloudflare

- **不要把间隔设太短**：同站最小间隔由 `HOST_MIN_INTERVAL`（默认 30s）+ `FETCH_JITTER_SECONDS`
  随机抖动控制；所有抓取**串行**执行，命中 403/429/503 会自动冷却退避。
- **普通 5 秒盾**：`cloudscraper` 通常可过。
- **硬盾（Turnstile / Managed Challenge）**：在 compose 中启用 `flaresolverr` 服务，
  并设置 `FLARESOLVERR_URL=http://flaresolverr:8191`。
- **换 IP**：设置 `CRAWL_PROXY` 走代理可进一步降低封禁概率。

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
  onelou.py           1lou 抓取：列表页→帖子→下载 .torrent→转磁力（需 Cookie）
  torrent.py          纯标准库 bencode 解析 + .torrent→magnet 转换
  clouddrive_client.py CloudDrive2 gRPC 封装（AddOfflineFiles）
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
