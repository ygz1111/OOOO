# ISO-NE 预测流程修复：已有服务器增量更新

此包用于已有 `/opt/smartgrid-server` 部署，不用于首次安装。
本地代码和离线测试通过不代表服务器已经更新；服务器真实接口验收仍需执行。

## 修复范围

- 自动在线预测共用一次计算，60秒缓存、并发合并；整点变化重新构造窗口。
- 负荷、电价时间是区间结束，光伏独立页是区间开始。09:40时HE09已过期，HE10代表09–10点。
- 光伏缺失不阻断负荷，价格模型运行失败不阻断负荷；但负荷模型训练输入本身含历史电价，历史电价完全缺失仍会影响新负荷预测。
- 最多6小时的尾部缺失可取昨日同小时观测补输入，并单独标记。历史内部缺口不凭空补齐。
- 此策略经过功能测试，未完成延迟场景的独立精度评估；“含估计输入”不代表与完整输入同等准确。
- 失败时只复用6小时内生成、尚未结束的预测，不平移日期、不凑满24点、不用演示数据替代。
- 回溯误差仅使用未补值的观测配对，并标注为事后天气回测，不代表在线预测精度。
- 请求等待后台计算最多约8秒；超时返回准备状态或有效缓存，前端约35秒自动重试。
- 入库不阻塞曲线；同份结果使用固定ID防重复。模型耗时与网络准备耗时分开。
- 页面自动隐藏已结束时段，显示最近观测、生成时间、输入估计与不足24小时覆盖。

## 更新前

确认云主机及网络服务未欠费暂停。无需开放新的公网端口。
不要重新运行 setup_env.py，不需要重装 Docker/Redis，不下载 TensorFlow，不重新训练。
备份与更新会占用额外少量磁盘空间，建议至少有3GB可用。
本包不含 `.env`、Compose、基础 Dockerfile、依赖列表、数据库和模型权重。
保留服务器已经调好的宿主机 Redis 连接与密码。

## 上传与应用

将 `smartgrid-forecast-update.zip` 上传到服务器 `/root`，然后执行：

```sh
smartgrid_update_dir=$(mktemp -d /tmp/smartgrid-update-XXXXXX)
python3 -m zipfile -e /root/smartgrid-forecast-update.zip "$smartgrid_update_dir"
sh "$smartgrid_update_dir/smartgrid-forecast-update/apply-forecast-update.sh"
```

脚本校验包内文件，备份现有代码和前端，为当前后端镜像保留恢复标签。
新镜像直接基于服务器现有可用镜像覆盖代码，不拉镜像、不安装依赖。
只重建后端容器和重启网页服务，不重启或删除 MySQL/Redis。
前端保留旧的带哈希资源文件，避免已有网页标签页突然找不到文件。

## 服务器验收（必须）

```sh
cd /opt/smartgrid-server
sh deploy/compose.sh ps
curl -fsS http://127.0.0.1:8080/api/health
sh deploy/compose.sh logs --tail=80 smartgrid-api
```

等待后端 healthy，然后从原来的访问方式登录网页，刷新一次。
检查三个预测页：应为当前美东日期；实测与估计明确区分；负荷与光伏按同一小时对齐。
等待跨一个整点再看，过期点应消失。资料准备中允许暂时没有曲线，不应伪造新数据。
如某项显示不可用，查看 input_quality.components 对应 reason；不可仅凭容器 healthy 判定预测正常。
不要把密码、令牌或完整 `.env` 发到聊天里；只提供状态和脱敏错误。

## 回退

更新失败时不要删除数据库。脚本打印了备份目录，最近一次路径也保存在
`/opt/smartgrid-server/backups/last-forecast-update.txt`。
检查路径确实是该项目的 `backups/forecast-...` 后，按实际值执行：

```sh
cd /opt/smartgrid-server
# 将下面路径替换为脚本实际打印的备份目录。
smartgrid_backup=/opt/smartgrid-server/backups/forecast-实际目录
docker image tag "$(cat "$smartgrid_backup/image-tag.txt")" smartgrid-personal-smartgrid-api:latest
tar -xzf "$smartgrid_backup/sources.tgz" -C /opt/smartgrid-server
sh deploy/compose.sh up -d --no-deps --no-build --pull never --force-recreate smartgrid-api
sh deploy/compose.sh restart web
```

回退不删除新增的未被旧版本引用的文件。保留备份镜像与源文件，验收后再决定是否清理。

## 已知边界

联网和数据发布仍依赖上游；长期中断或历史内部缺口会诚实显示不可用。
当前存量模型和数据库使用美东无偏移时间；夏令时重复/跳过小时的完整重构不在本次包中，不能宣称已验证这类日期的24个真实小时语义。
短时估计输入的精度需要额外实验；本次没有修改权重或训练集。
