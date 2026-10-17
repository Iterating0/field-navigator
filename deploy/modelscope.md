# ModelScope Studio Docker 部署说明

Field Navigator 的 ModelScope 适配使用 Docker 类型创空间。仓库根目录的
`Dockerfile` 可直接构建完整源码：构建阶段用 Node 22 编译 Vite 前端，运行阶段用
Python 3.12-slim 启动单个 FastAPI/uvicorn 进程。对外服务固定监听
`0.0.0.0:7860`，这是 ModelScope Docker 创空间要求的端口。

网页上传向导也可以使用 [四文件部署包](modelscope-bootstrap/README.md)。该包的
`Dockerfile` 在构建时从公开GitHub仓库获取固定提交的源码，避免上传文件夹时
丢失路径。四个文件须位于创空间根目录；应用源码和原Dockerfile仍在GitHub公开。
本次提交的源码固定于 `edac902c114f770b3837c6b44bf2e8b38515dfba`，包含一次有界 JSON 格式恢复，不会跟随分支变化。

## 配置依据

根目录的 `ms_deploy.json` 只声明 Docker 创空间所需的最小配置：

- `sdk_type`：`docker`
- `resource_configuration`：`platform/2v-cpu-16g-mem`
- `port`：`7860`

端口和字段依据 ModelScope 的官方部署 Skill：

- [@modelscope/modelscope-studio](https://modelscope.cn/skills/modelscope/modelscope-studio)
- [ModelScope Docker 创空间文档](https://modelscope.cn/docs/studios/docker)

Docker 类型创空间的账号绑定、实名认证、资源配额和创建操作属于平台侧步骤；
构建文件本身不会执行账号注册或提交比赛。2026-10-17 已在获得授权后通过平台网页部署公开创空间。
平台实际分配免费 2v CPU / 8G 内存，以上资源声明不代表可获得 16G。

## 本地检查

在仓库根目录执行：

```powershell
docker build -t field-navigator:modelscope .
docker run --rm -p 7860:7860 `
  -v field_navigator_modelscope:/mnt/workspace `
  field-navigator:modelscope
```

另开终端检查：

```powershell
python scripts/modelscope_smoke.py --url http://127.0.0.1:7860
```

脚本会检查配置文件和 Docker 服务的 `/api/health`、首页响应；它不会读取
`.env`，也不会调用 ModelScope API。

## 运行边界

镜像中的默认环境变量如下：

```text
FRONTEND_DIST_PATH=/app/frontend/dist
DATABASE_PATH=/mnt/workspace/field_navigator.sqlite3
LIVE_REQUEST_BUDGET=30
LIVE_MAX_CONCURRENCY=2
```

`LIVE_REQUEST_BUDGET=30` 和 `LIVE_MAX_CONCURRENCY=2` 是每个后台进程的保守
上限，用来避免公开 Demo 在未配置账户限额时无限消耗外部服务；它们不是按用户
计费或配额保证。单个 uvicorn worker 重启后会重新计数。离线演示和已经缓存的
结果仍可使用。需要外部服务时，在创空间变量/密钥管理中注入
`OPENALEX_API_KEY`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_THINKING`、
`LLM_RESPONSE_FORMAT` 和 `LLM_MAX_TOKENS`，不要把密钥写进前端、Dockerfile、Git 或镜像。
`OPENALEX_MAILTO` 为可选联系信息；本次公开演示没有复制私人邮箱。

SQLite 数据位于 `/mnt/workspace`，以便使用创空间的工作区持久化目录。容器以
非 root 用户运行。Dockerfile 使用白名单 `COPY`，不会把仓库根目录、`.git`、
`.env`、`node_modules` 或本地 SQLite 文件复制到镜像。

## 提交前检查

1. 确认仓库根目录含 `Dockerfile` 和 `ms_deploy.json`。
2. 本地完成 `docker build`，再用上面的 smoke 脚本检查服务。
3. 在 ModelScope 创建/更新 Docker 创空间时保持公开端口为 `7860`，并通过平台
   的变量或密钥界面填写外部服务配置。
4. 首次运行后检查首页、`/api/health`、离线 NHSE 演示和 SQLite 是否位于
   `/mnt/workspace`。

ModelScope 侧的实际构建日志、运行时资源、外部 API 可用性和数据持久化效果，
必须在目标创空间中单独验证；本地静态检查不代表已经完成云端部署。

## 平台访问边界

参赛演示入口使用 [ModelScope 创空间](https://modelscope.cn/studios/Iteraring0/field-navigator)。
2026-10-17 验证时，平台嵌入页面可正常访问应用与 `/api/health`；匿名直接请求
`ms.show` 返回平台 403，直接请求 API 推理域名返回平台 401。不要把这些地址当作
无需平台授权的公共 API，也不要在公开链接中复制平台临时令牌。真实链路验收应从
创空间嵌入界面操作，并明确区分离线演示、缓存、partial 和完整实时结果。
