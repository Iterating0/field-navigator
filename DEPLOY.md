# Field Navigator：部署说明

这套配置适用于**可以运行 Docker Compose 的 Linux 服务器**。前端容器提供网站，Nginx 将 `/api` 转发给后端；后端以非 root 身份运行，SQLite 保存在独立 Docker 数据卷中。OpenAlex 与兼容 OpenAI Chat Completions 的 LLM 都是可选环境变量。

## 交给自动部署器的说明

将下面整段复制到自动部署器。部署器若提供域名和 HTTPS 网关，可以用网关直接转发到网站容器 `80` 端口；若接管一台普通 VPS，请把服务器反向代理转发到 `127.0.0.1:8080`，并在代理上配置域名 HTTPS。

```text
请在这个 Git 仓库部署 Field Navigator。先阅读 DEPLOY.md、deploy/compose.yml 和 .env.example，再在 Linux Docker Compose 主机上构建并启动现有服务。

部署目录使用仓库根目录，执行：docker compose -f deploy/compose.yml up -d --build。
网站容器监听 80。普通 VPS 的主机反向代理转发到 127.0.0.1:8080；若部署面板提供容器域名网关，按面板要求通过其 80 端口路由，或在面板变量中设置 FIELD_NAVIGATOR_BIND=0.0.0.0、FIELD_NAVIGATOR_PORT=8080 并限制服务器防火墙只让网关访问该端口。后端端口 8000 仅供 Docker 内部访问，不要公开。

注意：这个 MVP 没有登录、账户或每人调用限额。Compose 与环境示例默认设置 LIVE_REQUEST_BUDGET=30、LIVE_MAX_CONCURRENCY=2，限制单个后台进程的非缓存实时请求总次数与并发；进程重启后重新计数，离线演示和有效缓存不消耗限额。本地内部使用可显式设为 0 关闭对应限制。用于内部试用时，可用部署面板的访问控制保护域名。不要把进程限额当作按用户配额或计费保证。

在服务器的仓库根目录创建 .env，从 .env.example 复制后填入使用者另外提供的服务密钥：OPENALEX_API_KEY、OPENALEX_MAILTO、LLM_API_KEY、LLM_BASE_URL、LLM_MODEL。如尚无 key，保留空值；内置 NHSE 离线演示仍可使用。不要生成密钥、猜测账户凭据、把 key 写入镜像或代码、在日志中打印 key，或提交服务器 .env。

保留 Compose 命名数据卷 field_navigator_data，数据库位于 /app/backend/data/field_navigator.sqlite3。重建或更新镜像时不要执行 docker compose down -v，也不要删除此数据卷。

构建后确认 docker compose -f deploy/compose.yml ps 显示服务健康，并通过网站 /api/health 检查后端健康。完成一次首页加载和 NHSE 离线示例探索，确认返回 8 篇示例论文、4 个研究分支。记录实际域名、HTTPS 状态、健康检查结果、启动命令和回滚/重启方式；不要声称 OpenAlex 或 LLM 外部 key 已验证，除非实际使用有效 key 完成了请求。
```

## 手动部署

1. 在服务器安装 Docker Engine 和 Docker Compose plugin，将仓库克隆到部署目录。进入仓库根目录。
2. 复制 `.env.example` 为 `.env` 并按需添加 key。离线演示不需要 key；实时 OpenAlex 搜索建议配置 `OPENALEX_API_KEY`，LLM 拆分配置 `LLM_API_KEY`、`LLM_MODEL` 与相应 `LLM_BASE_URL`。
3. 构建并启动：

   ```bash
   docker compose -f deploy/compose.yml up -d --build
   ```

4. 查看状态和日志：

   ```bash
   docker compose -f deploy/compose.yml ps
   docker compose -f deploy/compose.yml logs --tail=100 backend frontend
   ```

5. 网站默认只绑定本机 `127.0.0.1:8080`。把域名的 HTTPS 反向代理目标设为 `http://127.0.0.1:8080`。若部署平台自己负责 TLS 和容器路由，在平台的域名配置中把外部访问指向网站服务容器端口 `80`；后端 `8000` 仍只留在容器网络。
6. 打开 `https://你的域名/api/health`，预期响应为 `{"status":"ok", ...}`。首页支持 NHSE 离线示例；真实搜索及模型功能还取决于填入的外部服务 key。

要通过服务器公网 IP 直接测试且尚未配置反向代理，可在 `.env` 临时设置 `FIELD_NAVIGATOR_BIND=0.0.0.0`，服务器防火墙只开放所需端口；配置好 HTTPS 网关后删去此设置并重新部署。不要把 HTTP 登录凭据、`.env` 文件或 `8000` 后端端口暴露到公网。

更新应用时先备份重要数据，再运行第 3 步的命令。Docker 命名卷会在容器重建时保留 SQLite；`docker compose -f deploy/compose.yml down -v` 会删除数据库数据，仅在确定不需要数据时使用。

| 用途 | 可复制检查命令 | 正常结果 |
| --- | --- | --- |
| 运行状态 | `docker compose -f deploy/compose.yml ps` | `backend` 和 `frontend` 均 healthy |
| 后端健康 | `curl -fsS https://你的域名/api/health` | JSON `status` 为 `ok` |
| 浏览器 | 打开 `https://你的域名/` | Field Navigator 页面能加载 |
| 离线端到端 | 在应用中搜索 NHSE，选择离线演示 | 8 篇预设论文和 4 个研究分支 |

外部 key 是否配置由 `/api/health` 的布尔值确认；该接口不会返回 key 内容。若 HTTPS 由自动部署器的域名网关终止，请用实际分配的域名和端口，不要机械照抄 VPS 的 `127.0.0.1:8080` 地址。
