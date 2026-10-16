# Field Navigator：ModelScope 扁平上传包

这个目录是给 ModelScope Docker 创空间上传向导使用的最小扁平包，包含四个文件：

- `Dockerfile`
- `ms_deploy.json`
- `README.md`
- `LICENSE`

请在上传向导中选择这四个文件，并让 `Dockerfile` 和 `ms_deploy.json` 位于上传根目录。不要再套一层 `modelscope-bootstrap` 文件夹。

## 固定源码版本

构建时，`Dockerfile` 从公开仓库
[`Iterating0/field-navigator`](https://github.com/Iterating0/field-navigator.git)
以浅克隆方式获取以下固定 commit：

```text
fe4fd4f6c22f72133a25dcb97251af4cb1ab4e5c
```

随后以 detached checkout 构建前端。构建不会跟随 `main` 或其他分支变化。ModelScope 构建环境需要能够访问 GitHub 和 npm registry；上传包本身不携带应用源码。

## 运行配置

- Docker 服务监听 `0.0.0.0:7860`。
- 前端由同一个 FastAPI 容器提供。
- 容器以非 root 用户运行。
- SQLite 数据库位于 `/mnt/workspace/field_navigator.sqlite3`。
- `LIVE_REQUEST_BUDGET=30`、`LIVE_MAX_CONCURRENCY=2` 是每个后台进程的保守演示上限，不是按用户配额或计费保证；进程重启后重新计数。

外部服务的变量和密钥请在 ModelScope 创空间设置中注入，不要写入这个上传包、公开仓库、前端代码或镜像。

## 本地构建

在这个目录执行：

```powershell
docker build -t field-navigator:modelscope-bootstrap .
docker run --rm -p 7860:7860 `
  -v field_navigator_modelscope:/mnt/workspace `
  field-navigator:modelscope-bootstrap
```

实际创空间的构建日志、资源配额、外部 API 可用性和持久化效果仍需在 ModelScope 侧单独检查。
