
#!/bin/bash
#
# 智能电网负荷预测系统 - Redis数据库备份
# 
# 功能:
# - RDB持久化备份
# - AOF日志备份
# - 异地传输
# - 自动清理
#

# 设置严格模式
set -euo pipefail

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
export REDIS_HOST="localhost"
export REDIS_PORT="6379"
export REDIS_PASSWORD="redis_password"
export BACKUP_DIR="/var/lib/redis-backup"
export REDIS_DATA_DIR="/data"
export BACKUP_RETENTION_DAYS=7
export COMPRESS_FILES=true
export ENCRYPT_FILES=false
export REMOTE_BACKUP=true
export REMOTE_HOST="backups.smartgrid.tech"
export REMOTE_DIR="/backup/redis"

# 加载配置
if [ -f "/etc/redis/backup.conf" ]; then
    source "/etc/redis/backup.conf"
    log_info "已加载配置文件: /etc/redis/backup.conf"
fi

# 创建备份目录
mkdir -p "$BACKUP_DIR/rdb"
mkdir -p "$BACKUP_DIR/aof"  
mkdir -p "$BACKUP_DIR/logs"
mkdir -p "$BACKUP_DIR/encrypted"
mkdir -p "$BACKUP_DIR/snapshots"

date_str=$(date '+%Y%m%d_%H%M%S')
day_str=$(date '+%Y%m%d')

# 开始备份
log_info "======================================"
log_info "开始Redis数据库备份"
log_info "Redis服务器: $REDIS_HOST:$REDIS_PORT"
log_info "备份时间: $date_str"
log_info "======================================"

# ==========================
# 1. 连接检查
# ==========================

# 检查Redis连接
if ! redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" PING >/dev/null 2>&1; then
    log_error "Redis连接失败"
    exit 1
fi

log_info "✅ Redis连接正常"

# 检查Redis状态
redis_info=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" INFO)

if echo "$redis_info" | grep -q "loading:1"; then
    log_error "❌ Redis正在加载数据，无法备份"
    exit 1
fi

log_info "✅ Redis运行状态正常"

# ==========================
# 2. 获取Redis配置
# ==========================

# 获取RDB配置
rdb_dir=$(echo "$redis_info" | grep "^dir:" | cut -d: -f2 | tr -d '\r')
rdb_filename=$(echo "$redis_info" | grep "^dbfilename:" | cut -d: -f2 | tr -d '\r')

# 获取AOF配置  
aof_enabled=$(echo "$redis_info" | grep "^aof_enabled:" | cut -d: -f2 | tr -d '\r')
aof_file=$(echo "$redis_info" | grep "^aof_current_filename:" | cut -d: -f2 | tr -d '\r')

# 获取数据库信息
db_count=$(echo "$redis_info" | grep -c "^db[0-9]")
key_count=0

if [ "$db_count" -gt 0 ]; then
    key_count=$(echo "$redis_info" | grep "^db[0-9].*keys=" | awk -F'keys=' '{s += $2} END {gsub(/,.*/, "", s); print s}')
fi

log_info "Redis配置解析: RDB=$rdb_filename, AOF启用=$aof_enabled"
log_info "数据量: ${key_count} 个keys, ${db_count} 个数据库"

# ==========================
# 3. RDB持久化备份
# ==========================

log_info "开始RDB数据备份..."

time_start=$(date +%s)

# 触发BGSAVE生成新的RDB文件
if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" BGSAVE >/dev/null 2>&1; then
    log_info "✅ 已触发BGSAVE操作"
else
    log_warn "⚠️  BGSAVE触发失败，使用现有RDB文件"
fi

# 等待BGSAVE完成 (最多30秒)
wait_count=0
while [ $wait_count -lt 30 ] && [ "$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" INFO | grep 'bgsave_in_progress:1')" ]; do
    sleep 1
    wait_count=$((wait_count + 1))
done

# 复制RDB文件
rdb_source="${rdb_dir}/${rdb_filename}"
rdb_backup="${BACKUP_DIR}/rdb/${rdb_filename}_${date_str}"

if [ -f "$rdb_source" ]; then
    cp "$rdb_source" "$rdb_backup"
    
    rdb_size=$(stat -c%s "$rdb_backup" 2>/dev/null || echo 0)
    rdb_size_mb=$((rdb_size / 1024 / 1024))
    
    log_info "✅ RDB备份成功: ${rdb_size_mb}MB"
else
    log_error "❌ RDB文件不存在: $rdb_source"
    exit 1
fi

# ==========================
# 4. AOF日志备份
# ==========================

if [ "$aof_enabled" = "1" ]; then
    log_info "开始AOF日志备份..."
    
    # 触发BGREWRITEAOF
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" BGREWRITEAOF >/dev/null 2>&1; then
        log_info "✅ 已触发BGREWRITEAOF操作"
    fi
    
    # 等待完成 (最多60秒)
    wait_count=0
    while [ $wait_count -lt 60 ] && [ "$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" INFO | grep 'bgrewriteaof_in_progress:1')" ]; do
        sleep 1
        wait_count=$((wait_count + 1))
    done
    
    # 复制AOF文件
    aof_backup="${BACKUP_DIR}/aof/$(basename "$aof_file" .aof)_${date_str}.aof"
    
    if [ -f "$aof_file" ]; then
        cp "$aof_file" "$aof_backup"
        
        aof_size=$(stat -c%s "$aof_backup" 2>/dev/null || echo 0)
        aof_size_mb=$((aof_size / 1024 / 1024))
        
        log_info "✅ AOF备份成功: ${aof_size_mb}MB"
    else
        log_warn "⚠️  AOF文件不存在: $aof_file"
    fi
else
    log_info "AOF持久化已禁用"
fi

# ==========================
# 5. 元数据备份
# ==========================

# 生成INFO信息备份
info_file="${BACKUP_DIR}/logs/redis_info_${date_str}.json"
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" INFO > "$info_file"

log_info "✅ Redis状态信息已备份"

# ==========================  
# 6. 文件压缩
# ==========================

if [ "$COMPRESS_FILES" = true ]; then
    log_info "开始文件压缩..."
    
    compressed_files=()
    
    # 压缩RDB
    if [ -f "$rdb_backup" ] && pigz -p 4 "$rdb_backup"; then
        compressed_files+=("${rdb_backup}.gz")
        rm -f "$rdb_backup"
        log_info "✅ RDB文件已压缩"
    fi
    
    # 压缩AOF
    if [ -n "$aof_backup" ] && [ -f "$aof_backup" ] && pigz -p 4 "$aof_backup"; then
        compressed_files+=("${aof_backup}.gz") 
        rm -f "$aof_backup"
        log_info "✅ AOF文件已压缩"
    fi
fi

# ==========================
# 7. 文件加密
# ==========================

if [ "$ENCRYPT_FILES" = true ]; then
    log_info "开始文件加密..."
    
    if gpg --list-secret-keys redis-backup-key >/dev/null 2>&1; then
        for file in "$rdb_backup".gz "$aof_backup".gz; do
            if [ -f "$file" ] && gpg --batch --yes --encrypt --recipient "redis-backup-key" "$file"; then
                rm -f "$file"
                log_info "✅ 文件已加密: $file.gpg"
            fi
done
    else
        log_warn "⚠️ GPG密钥未配置，跳过加密"
    fi
fi

# ==========================
# 8. 异地备份
# ==========================

if [ "$REMOTE_BACKUP" = true ]; then
    log_info "开始异地备份传输..."
    
    if [ -f "/root/.ssh/backup_id_rsa" ]; then
        # 收集今日备份文件
        today_files=$(find "$BACKUP_DIR" -type f -name "*${day_str}*" | grep -E '(\.gz|\.gpg)$')
        
        if [ -n "$today_files" ]; then
            if rsync -avz --delete \
                -e "ssh -i /root/.ssh/backup_id_rsa -o StrictHostKeyChecking=no" \
                $today_files \
                "redis@$REMOTE_HOST:$REMOTE_DIR/${day_str}/"; then
                
                log_info "✅ 异地备份传输成功: $REMOTE_HOST"
            else
                log_error "❌ 异地备份传输失败"
            fi
        fi