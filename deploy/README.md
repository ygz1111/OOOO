# 个人服务器部署（Ubuntu 22.04 / 2核4G）

这是当前本地代码的部署副本，不是 GitHub 上的旧版本。只启动 Nginx 网页、
一个预测后端进程、MySQL、Redis。前端已经在本机编译，不必在服务器安装 Node。
生产模型为 tf_split_v1（负荷/电价）和 pv_v2，不训练模型。

## 当前验收边界

2026-10-03 已按当前项目重新完成前端类型检查、生产构建和 Compose 配置检查。
部署配置新增 `/app/backend/cache` 持久卷，保留有效预测缓存及实际输入归档；
后端健康检查使用 Python 标准库读取状态，拒绝 HTTP 200 中的 `unhealthy`，
允许 `healthy` / `degraded`，首次预测输入准备状态仍由网页如实展示。

本轮尚未连接服务器，未执行镜像下载、构建、模型加载、ISO 账号认证和网页验收。
正式部署需要确认服务器连接方式、是否已有实例、域名及公网 HTTPS 入口。
下面的默认配置仍为 SSH 隧道访问；仅执行 `up -d` 不代表网页已对公网开放。
4GB 是否足够长期使用，需要启动后观察实际内存和请求耗时。

## 本机生成最新上传包

先在 `frontend` 目录完成 `npm run type-check` 和 `npm run build`，再从项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy/package-server.ps1 -OutputPath .codex_tmp/smartgrid-server-latest.zip
```

脚本兼容 Windows PowerShell 5.1，打包当前本地代码、构建后的前端和现有模型。
可以通过 `OutputPath` 另存新包，避免覆盖旧上传包；不包含真实 `.env`、本地数据库、
运行日志、预测输入留档或训练原始数据。包中 `SHA256SUMS` 可用于核验所有文件。

## 上传后

将 smartgrid-server-upload.zip 上传到服务器 /root。首次安装时先确认
/opt/smartgrid-server 不存在，再在服务器执行：

```bash
python3 -m zipfile -e /root/smartgrid-server-upload.zip /opt
cd /opt/smartgrid-server
python3 deploy/setup_env.py
```

最后一条只在终端内询问 ISO-NE 邮箱和密码，密码输入不回显。数据库密码和
登录签名密钥自动随机生成到权限 600 的 .env；已有 .env 时不会覆盖。
不要把 .env 内容或带密码的 compose config 完整输出发到聊天中。

## 构建和启动

Ubuntu 仓库安装 Docker 后，如 `docker buildx version` 提示未找到，先执行
`apt-get install -y docker-buildx` 安装镜像构建组件。

```bash
sh deploy/compose.sh config --quiet
sh deploy/compose.sh pull mysql redis web
sh deploy/compose.sh build smartgrid-api
sh deploy/compose.sh up -d
sh deploy/compose.sh ps
curl -fsS http://127.0.0.1:8080/api/system/status
```

compose.sh 固定配置和环境文件的位置，避免误启原项目的完整监控套件。
如果拉取镜像超时，保留原错误并先处理仓库连通性，不添加未知第三方镜像源。
启动后检查 3/3 模型、24 小时负荷/电价/光伏输出及认证后的 ISO 数据获取。

## 仅自己访问

网页仅绑定服务器 127.0.0.1:8080。数据库、Redis、后端不发布端口。
阿里云安全组无需开放 80、8080、8000、3306、6379。
待另行配置 SSH 密钥，并将 SSH 访问来源限制为自己的电脑后，在自己电脑运行：

```text
ssh -N -L 18080:127.0.0.1:8080 <登录用户>@<服务器公网IP>
```

保持连接窗口打开，浏览器访问 http://127.0.0.1:18080 。
Workbench 免密会话不代表自己的电脑已经有 SSH 登录密钥，需要完成该连接步骤。
隧道只控制访问和加密，不免除服务器公网出网流量计费；免费流量额度仍需账号内核实。

## 数据和停止

服务器使用全新的独立数据库，本地账号、历史预测和原数据库未迁移；数据库初始化
只创建结构与角色权限，不插入示例天气数据。首次在网页注册自己的账号。
包中不含真实 .env、日志、node_modules、训练大文件或数据库备份。

新版本通过独立 `api-cache` 卷保存有效预测缓存和输入留档，后端重建不会删除该卷。
若更新已有旧部署，首次加入该卷前需把旧容器 `/app/backend/cache` 导出并保留；
新增卷不会自动搬运旧容器可写层中的数据。不要用首次安装步骤覆盖已有部署目录。

```bash
sh deploy/compose.sh stop
```

stop 保留数据。不要使用 down -v，它会删除服务器数据库卷。
云主机到期前另行备份数据库；停止应用不等同于停止云资源计费。
