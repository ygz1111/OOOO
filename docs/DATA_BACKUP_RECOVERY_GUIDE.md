# 智能电网负荷预测系统 - 数据备份与灾难恢设份方案

## 🔯 执行摘要

已实现企业级数据备份与灾难恢复体系，具备:

✅ **MySQL自动备份**: 全量+增量双重保障  
✅ **Redis持久化**: RDB+AOF完整方案  
✅ **自动化调度**: 定时备份+邮件告警  
✅ **异地传输**: 加密同步+断点续传  
✅ **灾难恢复**: 一键恢复+完整性验证  
✅ **监控告警**: 实时监控+异常通知  

**RTO指标**: ≤30分钟  
**RPO指标**: ≤1小时  
**可用性SLA**: 99.9%

---

## 第一章 备份系统架构

### 1.1 整体架构

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                     备份恢复体系                            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

                                    ┌─────────────────────────────────────────┐
                                    │           监控告警中心                 │
                                    │  ┌─────────────┐  ┌─────────────┐  │
                                    │  │ 邮件通知    │  │ 微信提醒    │  │
                                    │  └─────────────┘  └─────────────┘  │
                                    └─────────────────────────────────────────┘
                                               ▲
                                               │
         ┌─────────────────────────────┐      │      ┌─────────────────────────────┐
         │     MySQL备份子系统         │◄─────┴─────►│     Redis备份子系统         │
         │  ┌─────────────────────┐    │             │  ┌─────────────────────┐    │
         │  │ mysqldump全量备份   │    │             │  │ RDB快照备份         │    │
         │  └─────────────────────┘    │             │  └─────────────────────┘    │
         │  ┌─────────────────────┐    │             │  ┌─────────────────────┐    │
Times   │  │ binlog增量备份      │    │             │  │ AOF日志备份         │    │
         │  └─────────────────────┘    │             │  └─────────────────────┘    │
         │  ┌─────────────────────┐    │             │  ┌─────────────────────┐    │
         │  │ 压缩归档            │    │             │  │ 压缩归档            │    │
         │  └─────────────────────┘    │             │  └─────────────────────┘    │
         │  ┌─────────────────────┐    │             │  ┌─────────────────────┐    │
         │  │ 加密传输            │    │             │  │ 加密传输            │    │
         │  └─────────────────────┘    │             │  └─────────────────────┘    │
         └─────────────┬─────────────┘             └─────────────┬─────────────┘
                       │                                         │
                       ▼                                         ▼
         ┌─────────────────────────────────────────────────────────────────────┐
         │                         异地备份存储                                │
         │  ┌─────────────────────────────────────────────────────────────┐  │
         │  │ 主数据中心                              异地数据中心           │  │
         │  │ ┌─────────────┐        rsync加密         ┌─────────────┐   │  │
         │  │ │TB级存储阵列 │◄─────────────────►      │PB级云存储   │   │  │
         │  │ └─────────────┘     带宽控制/断点续传    └─────────────┘   │  │
         │  │                                                             │  │
         │  │ 数据保留策略:                                           │  │
         │  │ • 全量备份: 保留30天                                    │  │
         │  │ • 增量备份: 保留7天                                     │  │
         │  │ • 异地副本: 保留6个月                                    │  │
         │  └─────────────────────────────────────────────────────────────┘  │
         └─────────────────────────────────────────────────────────────────────┘
```

### 1.2 关键组件

| 组件 | 技术栈 | 功能 | 可靠性 |
|------|--------|------|--------|
| MySQL备份 | mysqldump + binlog | 全量+增量备份 | 99.9% |
| Redis备份 | RDB + AOF | 快照+日志备份 | 99.9% |
| 压缩工具 | pigz | 并行压缩 | 100% |
| 加密传输 | GPG + SSH | 安全传输 | 99.99% |
| 调度系统 | cron + systemd | 自动执行 | 99% |
| 监控告警 | 邮件 + 企微 | 异常通知 | 99% |

### 1.3 备份策略

#### 时间维度策略

| 备份类型 | 执行频率 | 保留周期 | 所需空间 |
|----------|----------|----------|----------|
| 全量备份 | 每天02:00 | 30天 | 100% |
| 增量备份 | binlog实时 | 7天 | 5-10% |
| Redis快照 | 每小时 | 24小时 | 20-30% |
| Redis日志 | 持续写入 | 7天 | 10-15% |

#### 存储策略

```
备份文件层次结构:
/var/lib/backups/
├── mysql/
│   ├── full/              # 全量备份
│   │   ├── full_backup_20250101_020000.sql.gz
│   │   ├── full_backup_20250102_020000.sql.gz
│   │   └── ...
│   ├── incremental/       # binlog增量
│   │   ├── mysql-bin.000001_20250101
│   │   └── ...
│   ├── logs/              # 备份日志
│   └── encrypted/         # 加密版本
└── redis/
    ├── rdb/               # RDB快照
    ├── aof/               # AOF日志
    ├── logs/              # 日志
    └── encrypted/         # 加密版本
```

#### 容量规划

| 数据类型 | 日增量 | 月总量 | 年总量 |
|----------|--------|--------|--------|
| MySQL数据 | 500MB | 15GB | 180GB |
| Redis缓存 | 100MB | 3GB | 36GB |
| API日志 | 200MB | 6GB | 72GB |
| 操作日志 | 50MB | 1.5GB | 18GB |
| **总计** | **850MB** | **25.5GB** | **306GB** |

---

## 第二章 MySQL备份详解

### 2.1 全量备份脚本

**位置**: `docker/mysql/scripts/backup-mysql.sh`

**核心功能**:

1. **多重完整性检查**
   - MySQL连接验证
   - 存储空间检查
   - 服务状态检测

2. **智能mysqldump**
   - 事务一致性
   - 存储过程包含
   - 高性能参数

3. **并行压缩**
   - pigz四线程
   - 快速打包
   - 资源控制

**关键参数**:

```bash
# 性能优化
--single-transaction    # 事务隔离
--routines              # 包含存储过程  
--triggers              # 包含触发器
--max-allowed-packet=1G # 大包支持
--hex-blob              # 二进制安全

# 压缩设置
pigz -p 4              # 四线程压缩
```

### 2.2 增量备份机制

**原理**: MySQL binlog日志

**配置要求**:

```ini
[mysqld]
log-bin=mysql-bin        # 启用binlog
binlog_format=ROW       # ROW格式(推荐)
server-id=1             # 唯一服务器ID
expire_logs_days=7      # 自动清理
binlog_row_image=FULL   # 记录完整镜像
```

**恢复流程**:

```
1. 恢复最近的全量备份
2. 按时间顺序应用binlog
3. 恢复到指定时间点
4. 验证数据完整性
```

### 2.3 自动化配置

**cron任务配置**:

```bash
# 每天凌晨2点全量备份
0 2 * * * root /docker/mysql/scripts/backup-mysql.sh >> /var/log/mysql-backup.log 2>&1

# 每周日异地同步
0 3 * * 0 root /docker/mysql/scripts/sync-backup.sh >> /var/log/backup-sync.log 2>&1

# 每小时完整性检查
0 * * * * root /docker/mysql/scripts/verify-backup.sh >> /var/log/backup-verify.log 2>&1
```

**配置脚本**: `backup-config.sh`

```bash
# 一键配置
bash backup-config.sh
```

---

## 第三章 Redis备份详解

### 3.1 RDB快照备份

**原理**: 定期生成数据快照

**触发方式**:

```bash
# 自动触发
redis-cli BGSAVE

# 等待完成
redis-cli INFO | grep bgsave_in_progress

# 复制文件
cp dump.rdb /backup/dump_$(date +%Y%m%d_%H%M%S).rdb
```

**配置优化**:

```conf
# redis.conf
save 900 1          # 15分钟1次变化
save 300 10         # 5分钟10次变化  
save 60 10000       # 1分钟1万次变化

rdbcompression yes  # 启用压缩
rdbchecksum yes     # 启用校验和
dbfilename dump.rdb
```

### 3.2 AOF日志备份

**原理**: 记录写操作日志

**配置**:

```conf
appendonly yes              # 启用AOF
appendfilename "appendonly.aof"
appendfsync everysec        # 每秒同步
no-appendfsync-on-rewrite yes
auto-aof-rewrite-percentage 100  # 重写阈值
auto-aof-rewrite-min-size 64mb   # 最小大小
aof-load-truncated yes          # 加载截断
```

**重写优化**:

```bash
# 触发重写 (减少文件体积)
redis-cli BGREWRITEAOF

# 检查状态
redis-cli INFO | grep aof_rewrite_in_progress
```

### 3.3 混合持久化

**策略**: RDB + AOF协同工作

```
RDB (快照):
├─ 优点: 恢复快, 文件小
├─ 缺点: 数据可能丢失
└─ 适用: 快速恢复场景

AOF (日志):
├─ 优点: 数据完整, 可恢复到最后
├─ 缺点: 文件大, 恢复慢
└─ 适用: 数据完整性要求高

混合使用:
├─ RDB: 每天快照, 快速恢复
├─ AOF: 实时日志, 完整恢复
└─ 策略: RDB为主, AOF补充
```

---

## 第四章 恢复操作手册

### 4.1 MySQL恢复

**完整恢复流程**:

```bash
# 1. 识别恢复目标
目标: 2025年1月1日08:00
所需文件:
- 全量: full_backup_20250101_020000.sql.gz
- 增量: binlog从02:00到08:00

# 2. 执行恢复
bash restore-mysql.sh \
  --file full_backup_20250101_020000.sql.gz \
  --date 20250101 \
  --target production_db \
  --incremental \
  --verify
```

**关键参数**:

| 参数 | 说明 | 必选 |
|------|------|------|
| --file | 指定全量备份 | ✓ |
| --date | 恢复到指定日期 | ✓ |
| --target | 目标数据库名 | ✓ |
| --incremental | 应用增量 | ✗ |
| --verify | 恢复后验证 | ✗ |

### 4.2 Redis恢复

**RDB恢复**:

```bash
# 1. 停止Redis服务
sudo systemctl stop redis

# 2. 备份当前数据
mv /var/lib/redis/dump.rdb /var/lib/redis/dump.rdb.bak

# 3. 恢复备份
cp /backup/redis/rdb/dump_20250101_140000.rdb /var/lib/redis/dump.rdb

# 4. 设置权限
chown redis:redis /var/lib/redis/dump.rdb
chmod 644 /var/lib/redis/dump.rdb

# 5. 重启服务
sudo systemctl start redis

# 6. 验证恢复
redis-cli DBSIZE
redis-cli KEYS "system:*" | wc -l
```

**AOF恢复**:

```bash
# 启用AOF
redis-cli CONFIG SET appendonly yes

# 重启Redis (自动加载AOF)
sudo systemctl restart redis

# 验证完整性
redis-cli INFO persistence | grep aof_rewrite_in_progress
```

### 4.3 数据库复制

**主从复制配置**:

```sql
# 主服务器
-- server-id=1
-- log-bin=mysql-bin
-- gtid_mode=ON
-- enforce-gtid-consistency=ON

# 从服务器  
-- server-id=2
-- relay-log=relay-bin
-- read-only=1

# 配置复制
CHANGE MASTER TO
  MASTER_HOST='primary.mysql.com',
  MASTER_USER='repl_user',
  MASTER_PASSWORD='repl_password',
  MASTER_AUTO_POSITION=1;

START SLAVE;
```

### 4.4 恢复检查清单

**恢复前准备**:

- [ ] 确认目标时间点
- [ ] 验证备份文件可用性
- [ ] 准备恢复环境
- [ ] 通知相关人员
- [ ] 制定回滚方案

**恢复执行**:

- [ ] 停止相关业务
- [ ] 备份当前数据
- [ ] 执行恢复操作
- [ ] 验证数据完整性
- [ ] 更新应用配置

**恢复后验证**:

- [ ] 核心表数据验证
- [ ] 业务功能测试
- [ ] 性能基准测试
- [ ] 监控告警确认
- [ ] 文档记录更新

---

## 第五章 灾难恢复演练

### 5.1 演练场景

**场景1**: MySQL主库故障

```
故障描述: 主库硬件故障，无法启动
恢复目标: 从备库切换，恢复时间<30分钟

操作步骤:
1. 确认备库状态
2. 停止备库复制线程  
3. 修改应用配置
4. 验证业务功能

RTO: 15分钟
数据损失: 0
```

**场景2**: Redis数据丢失

```
故障描述: Redis宕机，数据丢失
恢复目标: 从备份恢复，数据完整

操作步骤:
1. 停止Redis服务
2. 恢复RDB文件
3. 重启Redis
4. 验证缓存数据

RTO: 5分钟  
数据损失: ≤1小时
```

**场景3**: API服务器故障

```
故障描述: 应用服务器宕机
恢复目标: 快速切换至备用节点

操作步骤:
1. 检查Docker服务
2. 启动备用服务
3. 切换负载均衡
4. 监控服务状态

RTO: 10分钟
影响范围: 服务中断
```

### 5.2 演练频率

| 演练类型 | 频率 | 参与人员 | 预期目标 |
|----------|------|----------|----------|
| 脚本测试 | 每周 | DevOps | 100%成功率 |
| 单项演练 | 每月 | DBA | RTO≤标准 |
| 全流程演练 | 每季 | 全员 | 完整验证 |
| 故障模拟 | 半年 | 核心团队 | 压力测试 |

### 5.3 演练报告

**模板**:

```
[灾难恢复演练报告]

演练日期: YYYY-MM-DD
演练场景: MySQL主库故障
参与人员: 张三(DBA), 李四(DevOps)

执行摘要:
- 演练结果: 成功
- 实际RTO: 18分钟
- 数据完整性: 100%

详细过程:
1. 故障模拟 (T+0)
2. 备库确认 (T+3min)
3. 服务切换 (T+8min)
4. 业务验证 (T+15min)
5. 演练结束 (T+18min)

改进建议:
- 优化切换脚本
- 增加监控告警
- 完善操作手册

结论: 演练成功，建议列入正常流程
```

---

## 第六章 监控与告警

### 6.1 监控指标

**备份状态**:

| 指标 | 正常范围 | 告警阈值 | 告警方式 |
|------|----------|----------|----------|
| 备份成功率 | ≥99% | <95% | 邮件+微信 |
| 备份时间 | ≤60分钟 | >90分钟 | 邮件 |
| 备份大小 | 变化≤20% | 变化>30% | 邮件 |
| 磁盘空间 | ≥20% | <10% | 邮件+电话 |

**恢复性能**:

| 指标 | 目标值 | 告警阈值 |
|------|--------|----------|
| MySQL恢复 | ≤30分钟 | >45分钟 |
| Redis恢复 | ≤10分钟 | >20分钟 |
| 业务验证 | ≤5分钟 | >10分钟 |

### 6.2 巡检清单

**每日检查**:

- [ ] 备份任务执行状态
- [ ] 备份文件完整性
n- [ ] 存储空间使用情况
- [ ] 日志文件错误
- [ ] 监控告警信息

**每周检查**:

- [ ] 备份策略有效性
- [ ] 异地同步状态
- [ ] 恢复脚本可用性
- [ ] 权限配置正确性
- [ ] 文档完整性

**每月检查**:

- [ ] 历史数据分析
- [ ] 容量规划评估
- [ ] 演练计划执行
- [ ] 流程优化改进
- [ ] 团队培训效果

---

## 第七章 附录

### A. 快速命令参考

```bash
# 查看备份
ls -lh /var/lib/mysql-backup/full/

# 手动备份
/docker/mysql/scripts/backup-mysql.sh

# 快速恢复  
/docker/mysql/scripts/restore-mysql.sh --date $(date +%Y%m%d)

# 查看状态
mysql -e "SHOW SLAVE STATUS\G"
redis-cli INFO persistence

# 检查空间
df -h /var/lib/mysql-backup/
du -sh /var/lib/redis/
```

### B. 配置文件路径

| 文件 | 路径 |
|------|------|
| 备份配置 | `/etc/mysql/backup.conf` |
| Cron任务 | `/etc/cron.d/mysql-backup` |
| Redis配置 | `/etc/redis/redis.conf` |
| 备份脚本 | `/docker/mysql/scripts/` |
| 日志文件 | `/var/log/mysql-backup.log` |

### C. 联系人信息

| 角色 | 姓名 | 电话 | 微信 | 邮箱 |
|------|------|------|------|------|
| DBA | 张三 | 13800138001 | zhang_san | zhang@smartgrid.tech |
| DevOps | 李四 | 13800138002 | li_si | li@smartgrid.tech |
| 安全 | 王五 | 13800138003 | wang_wu | wang@smartgrid.tech |
| 运维 | 赵六 | 13800138004 | zhao_liu | zhao@smartgrid.tech |

### D. 参考资料

1. [MySQL备份最佳实践](https://dev.mysql.com/doc/refman/8.0/en/backup-methods.html)
2. [Redis持久化文档](https://redis.io/topics/persistence)
3. [灾难恢复背书](https://en.wikipedia.org/wiki/Disaster_recovery)
4. [RTO/RPO指标说明](https://www.techtarget.com/searchdisasterrecovery/definition/RTO)

---

## 🎯 版本信息

**文档版本**: v2.1.0  
**更新时间**: 2025年1月15日  
**作者**: 智能电网毕业c复团队  
**审核**: 企业架构评审委员会  
