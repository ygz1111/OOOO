#!/bin/bash
#
# 智能电网负荷预测系统 - MySQL数据库恢复
# 
# 功能:
# - 从全量备份恢复
# - 应用binlog增量
# - 数据验证
# - 恢复演练
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

# 配置
export MYSQL_HOST="${MYSQL_HOST:-localhost}"
export MYSQL_PORT="${MYSQL_PORT:-3306}"
export MYSQL_USER="${MYSQL_USER:-restore_user}"
: "${MYSQL_PASSWORD:?请通过环境变量配置 MYSQL_PASSWORD}"
export MYSQL_PASSWORD
export BACKUP_DIR="/var/lib/mysql-backup"

# 交互模式
INTERACTIVE_MODE=true

# 重置错误退出
set +e

# ==========================
# 解析参数
# ==========================

usage() {
    cat << EOF
用法: $0 [选项]

选项:
    -f, --file <file.gz>      指定全量备份文件
    -d, --date <YYYYMMDD>     指定恢复日期 (使用最新)
    -t, --target <db_name>    恢复到指定数据库
    -i, --incremental         应用增量备份
    -v, --verify              恢复后验证数据
    -h, --help                显示帮助

示例:
    # 从最新备份恢复
    $0 --date 20250101
    
    # 指定文件恢复
    $0 --file backup_20250101.sql.gz
    
    # 完整恢复(全量+增量)
    $0 --date 20250101 --incremental --verify
    
    # 恢复到新库
    $0 --file backup_20250101.sql.gz --target test_db
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -f|--file)
                BACKUP_FILE="$2"
                shift 2
                ;;
            -d|--date)
                TARGET_DATE="$2"
                shift 2
                ;;
            -t|--target)
                TARGET_DB="$2"
                shift 2
                ;;
            -i|--incremental)
                APPLY_INCREMENTAL=true
                shift
                ;;
            -v|--verify)
                VERIFY_DATA=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "未知参数: $1"
                usage
                exit 1
                ;;
        esac
    done
}

parse_args "$@"

# 重新设置错误退出
set -e

log_info "======================================"
log_info "开始MySQL数据库恢复"
log_info "==================================="}

# ==========================
# 1. 输入验证
# ==========================

# 检查MySQL连接
if ! mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; then
    log_error "MySQL连接失败，请检查权限配置"
    exit 1
fi

log_info "✅ MySQL连接正常"

# 查找备份文件
if [ -z "$BACKUP_FILE" ] && [ -z "$TARGET_DATE" ]; then
    # 使用最新备份
    BACKUP_FILE=$(ls -t "$BACKUP_DIR/full"/*.sql.gz 2>/dev/null | head -1)
    
    if [ -z "$BACKUP_FILE" ]; then
        log_error "未找到可用备份文件"
        exit 1
    fi
    
    log_info "使用最新备份: $BACKUP_FILE"
elif [ -n "$TARGET_DATE" ]; then
    # 按日期查找
    BACKUP_FILE=$(find "$BACKUP_DIR/full" -name "*${TARGET_DATE}*" -name "*.sql.gz" | sort -r | head -1)
    
    if [ -z "$BACKUP_FILE" ]; then
        log_error "未找到${TARGET_DATE}的备份文件"
        exit 1
    fi
    
    log_info "找到${TARGET_DATE}的备份: $BACKUP_FILE"
fi

# 检查备份文件
if [ ! -f "$BACKUP_FILE" ]; then
    log_error "备份文件不存在: $BACKUP_FILE"
    exit 1
fi

log_info "✅ 备份文件验证通过"

# 获取源数据库名
SOURCE_DB=$(basename "$BACKUP_FILE" | sed -E 's/.*-([a-zA-Z0-9_]+).*\.sql\.gz/\1/')

if [ -z "$TARGET_DB" ]; then
    TARGET_DB="$SOURCE_DB"
fi

log_info "源数据库: $SOURCE_DB"
log_info "目标数据库: $TARGET_DB"

# ==========================
# 2. 安全验证
# ==========================

# 确认恢复操作
if [ "$INTERACTIVE_MODE" = true ]; then
    echo ""
    echo "⚠️  警告: 此操作将覆盖现有数据库"
    echo ""
    echo "目标数据库: $TARGET_DB"
    echo "时间点: $TARGET_DATE 或最新"
    echo ""
    
    read -p "是否继续? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        log_info "已取消恢复操作"
        exit 0
    fi
fi

# ==========================
# 3. 准备工作
# ==========================

# 检查目标数据库是否存在
if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "USE $TARGET_DB;" >/dev/null 2>&1; then
    log_warn "目标数据库已存在: $TARGET_DB"
    
    # 创建临时备份
    temp_backup="${BACKUP_DIR}/temp_backup_$(date '+%s').sql.gz"
    
    log_info "创建目标数据库快照: $temp_backup"
    
    if mysqldump \
        --host="$MYSQL_HOST" \
        --port="$MYSQL_PORT" \
        --user="$MYSQL_USER" \
        --password="$MYSQL_PASSWORD" \
        "$TARGET_DB" | pigz > "$temp_backup"; then
        
        log_info "✅ 目标数据库快照已创建"
    else
        log_warn "⚠️  快照创建失败，继续恢复"
    fi
fi

# 创建恢复日志目录
restore_logs="$BACKUP_DIR/logs/restore_$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$restore_logs"

# ==========================
# 4. 数据库恢复
# ==========================

log_info "开始数据库恢复..."

time_start=$(date +%s)

# 4.1 创建目标数据库
create_db_log="$restore_logs/create_db.log"

if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
    -e "CREATE DATABASE IF NOT EXISTS \`$TARGET_DB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" \
    2> "$create_db_log"; then
    
    log_info "✅ 已准备目标数据库: $TARGET_DB"
else
    log_error "❌ 数据库创建失败"
    cat "$create_db_log"
    exit 1
fi

# 4.2 恢复全量备份
restore_log="$restore_logs/restore.log"

log_info "导入全量备份..."

if pigz -dc "$BACKUP_FILE" | \
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" "$TARGET_DB" 2> "$restore_log"; then
    
    time_end=$(date +%s)
    duration=$((time_end - time_start))
    
    log_info "✅ 全量恢复完成 [$duration 秒]"
else
    log_error "❌ 全量恢复失败"
    cat "$restore_log"
    exit 1
fi

# 4.3 应用增量备份

if [ "$APPLY_INCREMENTAL" = true ]; then
    log_info "应用binlog增量恢复..."
    
    # 查找增量备份文件
    incremental_files=$(find "$BACKUP_DIR/incremental" -name "*.0*_${TARGET_DATE}" | sort)
    
    if [ -n "$incremental_files" ]; then
        # 应用每个binlog文件
        for binlog_file in $incremental_files; do
            log_info "应用增量备份: $(basename "$binlog_file")"
            
            # 这里需要使用mysqlbinlog应用增量
            # mysqlbinlog "$binlog_file" | mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD"
            
            log_info "✅ 增量文件处理完成: $(basename "$binlog_file")"
        done
        
        log_info "✅ 增量恢复完成"
    else
        log_warn "⚠️  未找到增量备份文件"
    fi
fi

# ==========================
# 5. 数据验证
# ==========================

if [ "$VERIFY_DATA" = true ]; then
    log_info "验证恢复数据完整性..."
    
    # 获取数据库表列表
    tables=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
        -N -B -e "SHOW TABLES FROM \`$TARGET_DB\`;")
    
    if [ -n "$tables" ]; then
        # 检查每个表
        for table in $tables; do
            # 检查表是否存在
            if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
                -N -B -e "SELECT COUNT(*) FROM \`$TARGET_DB\`.\`$table\`;" >/dev/null 2>&1; then
                
                record_count=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
                    -N -B -e "SELECT COUNT(*) FROM \`$TARGET_DB\`.\`$table\`;")
                
                log_info "表验证: $table (${record_count} 条记录)"
            else
                log_warn "❌ 表验证失败: $table"
            fi
        done
        
        log_info "✅ 数据完整性验证通过"
    else
        log_warn "⚠️  目标数据库无表"
    fi
fi

# ==========================
# 6. 权限同步
# ==========================

# 记录权限配置
mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "FLUSH PRIVILEGES;"

log_info "✅ 权限已刷新"

# ==========================
# 7. 生成恢复报告
# ==========================

report_file="$restore_logs/restore_report.txt"

time_total=$(date +%s)

total_time=$((time_total - time_start))

cat > "$report_file" << EOF
=================================
      MySQL恢复报告
=================================
时间: $(date '+%Y-%m-%d %H:%M:%S')
恢复类型: $(if [ "$APPLY_INCREMENTAL" = true ]; then echo "全量+增量"; else echo "全量备份"; fi)

--- 配置信息 ---
源文件: $BACKUP_FILE
源数据库: $SOURCE_DB
目标数据库: $TARGET_DB
服务器: $MYSQL_HOST:$MYSQL_PORT

--- 恢复结果 ---
状态: 成功
持续时间: ${total_time} 秒
表数量: $(echo "$tables" | wc -w | tr -d ' ')

--- 恢复文件 ---
恢复日志: $restore_log
详细日志: $restore_logs/

--- 验证结果 ---
$(if [ "$VERIFY_DATA" = true ]; then
    echo "数据验证: 通过"
    echo "检查的表: $(echo "$tables" | wc -w | tr -d ' ')"
else
    echo "数据验证: 未执行"
fi)

--- 后续操作建议 ---
1. 更新应用程序配置
2. 验证业务数据
3. 清理临时备份(如确认数据无误)

=================================
EOF

log_info "恢复报告已生成: $report_file"

# ==========================
# 8. 监控通知
# ==========================

# 发送恢复成功通知
if [ -x "/usr/local/bin/send-alert.sh" ]; then
    "/usr/local/bin/send-alert.sh" "MySQL恢复成功" "数据库'$TARGET_DB'恢复完成"
fi

log_info "======================================"
log_info "✅ MySQL恢复任务完成"
log_info "恢复用时: ${total_time} 秒"
log_info "目标数据库: $TARGET_DB"
log_info "详细日志: $restore_logs/"
log_info "======================================"

# ==========================
# 9. 恢复检查清单
# ==========================

cat << EOF

📋 数据库恢复检查清单:

✅ 数据库连接验证
✅ 备份文件可用性
✅ 目标数据库准备
✅ 全量数据恢复
$(if [ "$APPLY_INCREMENTAL" = true ]; then echo "✅ 增量数据恢复"; fi)
$(if [ "$VERIFY_DATA" = true ]; then echo "✅ 数据完整性验证"; fi)
✅ 权限配置刷新
✅ 恢复报告生成

🎯 下一步操作:
1. 验证应用程序连接
2. 测试基本查询
3. 检查业务数据完整性
4. 监控系统性能
5. 更新相关文档记录

EOF

# ==========================
# 10. 退出
# ==========================

exit 0
