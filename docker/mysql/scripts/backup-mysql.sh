#!/bin/bash
#
# 智能电网负荷预测系统 - MySQL数据库备份
# 
# 功能:
# - 全库备份 (mysqldump)
# - 增量备份 (binlog)
# - 压缩归档
# - 自动清理
# - 异地传输
#
# 部署位置: docker/mysql/scripts/backup-mysql.sh
# 配置cron自动执行: 每天凌晨2点备份
#

# 设置错误退出
set -e

# 日志函数
log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $1"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

log_warn() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $1"
}

# 配置环境变量
export MYSQL_HOST="localhost"
export MYSQL_PORT="3306"
export MYSQL_USER="backup_user"
export MYSQL_PASSWORD="backup_password"
export MYSQL_DATABASE="load_prediction_db"

# 备份配置
export BACKUP_DIR="/var/lib/mysql-backup"
export BACKUP_RETENTION_DAYS=30
export COMPRESS_FILES=true
export ENCRYPT_FILES=false
export REMOTE_BACKUP=false
export REMOTE_HOST="backups.smartgrid.tech"
export REMOTE_DIR="/backup/mysql"

# 加载配置(如果存在)
if [ -f "/etc/mysql/backup.conf" ]; then
    source "/etc/mysql/backup.conf"
    log_info "已加载配置文件: /etc/mysql/backup.conf"
fi

# 创建备份目录
mkdir -p "$BACKUP_DIR/full"
mkdir -p "$BACKUP_DIR/incremental"
mkdir -p "$BACKUP_DIR/logs"
mkdir -p "$BACKUP_DIR/encrypted"

date_str=$(date '+%Y%m%d_%H%M%S')
day_str=$(date '+%Y%m%d')

log_info "======================================"
log_info "开始MySQL数据库备份"
log_info "数据库: $MYSQL_DATABASE"
log_info "备份类型: 全量+增量"
log_info "备份时间: $date_str"
log_info "======================================"

# ==========================
# 1. 完整性检查
# ==========================

# 检查MySQL连接
if ! mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; then
    log_error "MySQL连接失败，请检查配置: $MYSQL_HOST:$MYSQL_PORT"
    exit 1
fi

log_info "✅ MySQL连接正常"

# 检查存储空间
available_space=$(df "$BACKUP_DIR" | tail -1 | awk '{print $4}')
available_space_gb=$((available_space / 1024 / 1024))

if [ $available_space_gb -lt 10 ]; then
    log_warn "⚠️ 存储空间不足: ${available_space_gb}GB (至少需要10GB)"
else
    log_info "✅ 存储空间充足: ${available_space_gb}GB"
fi

# ==========================
# 2. 全量备份
# ==========================

log_info "开始全量备份..."

full_backup_file="$BACKUP_DIR/full/full_backup_${date_str}.sql"
full_backup_log="$BACKUP_DIR/logs/full_${date_str}.log"

time_start=$(date +%s)

if mysqldump \
    --host="$MYSQL_HOST" \
    --port="$MYSQL_PORT" \
    --user="$MYSQL_USER" \
    --password="$MYSQL_PASSWORD" \
    --single-transaction \
    --routines \
    --triggers \
    --events \
    --hex-blob \
    --set-gtid-purged=OFF \
    --max-allowed-packet=1G \
    "$MYSQL_DATABASE" \
    > "$full_backup_file" \
    2> "$full_backup_log"
then
    time_end=$(date +%s)
    duration=$((time_end - time_start))
    
    # 检查备份文件大小
    backup_size=$(stat -c%s "$full_backup_file")
    backup_size_mb=$((backup_size / 1024 / 1024))
    
    log_info "✅ 全量备份成功 [$duration 秒]: ${backup_size_mb}MB"
    
    # 验证备份完整性
    if ! grep -q "Dump completed" "$full_backup_log" && ! [ -s "$full_backup_file" ]; then
        log_error "⚠️ 备份文件可能不完整"
        exit 1
    fi
    
else
    log_error "❌ 全量备份失败"
    cat "$full_backup_log"
    exit 1
fi

# ==========================
# 3. binlog增量备份
# ==========================

log_info "开始binlog增量备份..."

# 获取当前binlog位置
binlog_status=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -BN -e "SHOW MASTER STATUS")

if [ -n "$binlog_status" ]; then
    current_file=$(echo "$binlog_status" | awk '{print $1}')
    current_pos=$(echo "$binlog_status" | awk '{print $2}')
    
    log_info "当前binlog: $current_file (pos: $current_pos)"
    
    # 刷新日志
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "FLUSH LOGS"
    
    # 查找最新的binlog文件
    binlog_dir=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -BN -e "SHOW VARIABLES LIKE 'log_bin_basename'" | awk '{print $2}' | xargs dirname)
    
    if [ -d "$binlog_dir" ]; then
        # 复制最新的binlog文件
        latest_binlog=$(ls -t "$binlog_dir"/*.0* 2>/dev/null | head -1)
        
        if [ -f "$latest_binlog" ]; then
            binlog_name=$(basename "$latest_binlog")
            cp "$latest_binlog" "$BACKUP_DIR/incremental/${binlog_name}_${date_str}"
            log_info "✅ binlog增量备份成功: $binlog_name"
        fi
    fi
else
    log_warn "⚠️ binlog未启用或获取失败"
fi

# ==========================
# 4. 文件压缩
# ==========================

if [ "$COMPRESS_FILES" = true ]; then
    log_info "开始文件压缩..."
    
    # 压缩SQL文件
    if [ -f "$full_backup_file" ]; then
        pigz -p 4 "$full_backup_file" &
    fi
    
    # 等待压缩完成
    wait
    
    if [ -f "${full_backup_file}.gz" ]; then
        rm -f "$full_backup_file"
        log_info "✅ SQL文件已压缩: ${full_backup_file}.gz"
    fi
fi

# ==========================
# 5. 文件加密
# ==========================

if [ "$ENCRYPT_FILES" = true ]; then
    log_info "开始文件加密..."
    
    # 检查GPG密钥
    if gpg --list-secret-keys backup-key >/dev/null 2>&1; then
        backup_files=$(find "$BACKUP_DIR/full" "$BACKUP_DIR/incremental" -type f -newer "$BACKUP_DIR" -name '*.gz' -o -name '*.sql')
        
        for file in $backup_files; do
            if ! gpg --batch --yes --encrypt --recipient "backup-key" "$file"; then
                log_warn "⚠️ 文件加密失败: $file"
            else
                # 加密成功后删除原文
                rm -f "$file"
                log_info "✅ 文件已加密: ${file}.gpg"
            fi
        done
    else
        log_warn "⚠️ GPG密钥未配置，跳过加密"
    fi
fi

# ==========================
# 6. 异地备份
# ==========================

if [ "$REMOTE_BACKUP" = true ]; then
    log_info "开始异地备份传输..."
    
    # 检查SSH密钥
    if [ -f "/root/.ssh/backup_id_rsa" ]; then
        remote_files=$(find "$BACKUP_DIR/full" "$BACKUP_DIR/incremental" -type f -mtime -1)
        
        if [ -n "$remote_files" ]; then
            if rsync -avz --delete \
                -e "ssh -i /root/.ssh/backup_id_rsa -o StrictHostKeyChecking=no" \
                $remote_files \
                "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"
            then
                log_info "✅ 异地备份传输成功: $REMOTE_HOST"
            else
                log_error "❌ 异地备份传输失败"
            fi
        fi
    else
        log_warn "⚠️ SSH密钥未配置，跳过异地备份"
    fi
fi

# ==========================
# 7. 自动清理
# ==========================

log_info "开始清理过期备份..."

# 清理过期备份文件
find "$BACKUP_DIR/full" -name "*.sql" -o -name "*.gz" -o -name "*.gpg" | \
    find -type f -mtime +$BACKUP_RETENTION_DAYS | while read -r file; do
        rm -f "$file"
        log_info "清理过期备份: $file"
done

# 清理增量备份 (保留最近7天)
find "$BACKUP_DIR/incremental" -type f -mtime +7 | while read -r file; do
    rm -f "$file"
    log_info "清理过期增量: $file"
done

# 清理过期日志
find "$BACKUP_DIR/logs" -name "*.log" -mtime +$BACKUP_RETENTION_DAYS | while read -r file; do
    rm -f "$file"
    log_info "清理过期日志: $file"
done

# ==========================
# 8. 完整性检查
# ==========================

log_info "验证备份完整性..."

# 检查最新备份文件
latest_backup=$(ls -t "$BACKUP_DIR/full"/*.sql.gz 2>/dev/null | head -1)

if [ -f "$latest_backup" ]; then
    # 测试解压
    if pigz -t "$latest_backup" 2>/dev/null; then
        log_info "✅ 备份文件完整性验证通过: $latest_backup"
    else
        log_error "❌ 备份文件损坏: $latest_backup"
    fi
else
    log_error "❌ 未发现有效备份文件"
fi

# ==========================
# 9. 生成备份报告
# ==========================

log_info "生成备份报告..."

report_file="$BACKUP_DIR/logs/backup_report_${date_str}.txt"

cat > "$report_file" << EOF
=================================
      MySQL备份报告 
=================================
时间: $(date '+%Y-%m-%d %H:%M:%S')
数据库: $MYSQL_DATABASE
服务器: $MYSQL_HOST:$MYSQL_PORT

--- 备份信息 ---
状态: 成功
持续时间: $duration 秒

--- 文件信息 ---
备份文件: ${full_backup_file}.gz
文件大小: ${backup_size_mb}MB
binlog: $current_file

--- 存储信息 ---
备份目录: $BACKUP_DIR
可用空间: ${available_space_gb}GB
保留天数: ${BACKUP_RETENTION_DAYS}天

--- 传输信息 ---
异地备份: $(if [ "$REMOTE_BACKUP" = true ]; then echo "已配置"; else echo "未启用"; fi)
远程主机: $REMOTE_HOST

--- 日志位置 ---
详细日志: ${full_backup_log}
错误日志: ${full_backup_log}
报告存档: $report_file

=================================
EOF

log_info "备份报告已生成: $report_file"

# ==========================
# 10. 监控告警
# ==========================

# 发送备份成功通知 (如果配置)
if [ -x "/usr/local/bin/send-alert.sh" ]; then
    "/usr/local/bin/send-alert.sh" "MySQL备份成功" "数据库'$MYSQL_DATABASE'备份完成"
fi

log_info "======================================"
log_info "✅ MySQL备份任务完成"
log_info "======================================"

# 退出成功
exit 0
