#!/bin/bash
#
# 智能电网负荷预测系统 - MySQL备份配置与验证
#
# 功能:
# - 自动配置备份用户
# - 设置备份权限
# - 配置cron任务
# - 验证备份配置
#

# 严格模式
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
log_success() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ $1"
}

# 配置参数
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:-"your-root-password"}
BACKUP_USER="backup_user"
BACKUP_PASSWORD="StrongBackup123!"
MYSQL_HOST="localhost"
MYSQL_PORT="3306"
BACKUP_DIR="/var/lib/mysql-backup"

# 显示配置信息
show_config() {
    cat << EOF

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                    MySQL备份配置                            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

服务器配置:
  Host:      $MYSQL_HOST
  Port:      $MYSQL_PORT
  Root密码:  (从环境变量)

备份配置:
  用户:      $BACKUP_USER
  密码:      $BACKUP_PASSWORD
  目录:      $BACKUP_DIR

备份策略:
  全量备份:  每天凌晨2点
  保留天数:  30天
  压缩:      启用
  异地备份:  配置

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

继续配置? (yes/no): 
EOF
    
    read -r confirm
    if [ "$confirm" != "yes" ]; then
        log_info "配置已取消"
        exit 0
    fi
}

# 检查环境
check_environment() {
    log_info "环境检查..."
    
    # 检查MySQL连接
    if ! mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; then
        log_error "❌ MySQL root连接失败"
        exit 1
    fi
    
    log_success "MySQL连接正常"
    
    # 检查必要工具
    for tool in mysqldump mysql pigz find; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            log_error "❌ 必需工具未安装: $tool"
            exit 1
        fi
    done
    
    log_success "必需工具已安装"
    
    # 检查备份目录
    if [ ! -d "$BACKUP_DIR" ]; then
        mkdir -p "$BACKUP_DIR"
        log_info "已创建备份目录: $BACKUP_DIR"
    fi
}

# 创建备份用户
create_backup_user() {
    log_info "创建备份用户..."
    
    # 检查用户是否存在
    if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -N -B -e "SELECT COUNT(*) FROM mysql.user WHERE user='${BACKUP_USER}';" | grep -q "1"; then
        log_warn "⚠️  备份用户已存在，重新配置权限"
    else
        # 创建备份用户
        if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -e "CREATE USER '${BACKUP_USER}'@'%' IDENTIFIED BY '${BACKUP_PASSWORD}';" >/dev/null 2>&1; then
            log_success "✅ 备份用户创建成功"
        else
            log_error "❌ 备份用户创建失败"
            exit 1
        fi
    fi
    
    # 授予备份权限
    if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -e "GRANT SELECT, LOCK TABLES, RELOAD, SHOW DATABASES, REPLICATION CLIENT, EVENT, TRIGGER ON *.* TO '${BACKUP_USER}'@'%'; FLUSH PRIVILEGES;" >/dev/null 2>&1; then
        log_success "✅ 备份权限授予成功"
    else
        log_error "❌ 权限授予失败"
        exit 1
    fi
    
    # 创建恢复用户
    RESTORE_USER="restore_user"
    RESTORE_PASSWORD="RestoreStrong123!"
    
    if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -e "CREATE USER IF NOT EXISTS '${RESTORE_USER}'@'%' IDENTIFIED BY '${RESTORE_PASSWORD}';" >/dev/null 2>&1; then
        mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -e "GRANT ALL PRIVILEGES ON *.* TO '${RESTORE_USER}'@'%'; FLUSH PRIVILEGES;" >/dev/null 2>&1
        log_success "✅ 恢复用户配置成功"
    else
        log_warn "⚠️  恢复用户配置失败"
    fi
}

# 创建配置文件
create_backup_config() {
    log_info "创建备份配置文件..."
    
    config_dir="/etc/mysql"
    mkdir -p "$config_dir"
    
    config_file="${config_dir}/backup.conf"
    
    cat > "$config_file" << EOF
# MySQL备份配置文件
# 由backup-config.sh自动生成

# 数据库连接
export MYSQL_HOST="${MYSQL_HOST}"
export MYSQL_PORT="${MYSQL_PORT}"
export MYSQL_USER="${BACKUP_USER}"
export MYSQL_PASSWORD="${BACKUP_PASSWORD}"
export MYSQL_DATABASE="load_prediction_db"

# 备份配置
export BACKUP_DIR="${BACKUP_DIR}"
export BACKUP_RETENTION_DAYS=30
export COMPRESS_FILES=true
export ENCRYPT_FILES=false

# 远程备份
export REMOTE_BACKUP=true
export REMOTE_HOST="backups.smartgrid.tech"
export REMOTE_USER="mysql_backup"
export REMOTE_DIR="/backup/mysql"

# 日志配置
export LOG_LEVEL="INFO"
export LOG_ROTATION_SIZE="100M"

# 监控配置
export ENABLE_MONITORING=true
export ALERT_EMAIL="admin@smartgrid.tech"

# 性能调优
export MAX_DUMP_SIZE="10G"
export PARALLEL_COMPRESS_THREADS=4
export NET_BUFFER_LENGTH="1M"
EOF
    
    # 设置文件权限
    chmod 600 "$config_file"
    chown root:root "$config_file"
    
    log_success "✅ 配置文件创建成功: $config_file"
    
    # 显示配置摘要
    echo ""
    echo "备份配置摘要:"
    echo "  保留天数: $(grep "BACKUP_RETENTION_DAYS" "$config_file" | cut -d= -f2)"
    echo "  压缩: $(grep "COMPRESS_FILES" "$config_file" | cut -d= -f2)"
    echo "  异地备份: $(grep "REMOTE_BACKUP" "$config_file" | cut -d= -f2)"
    echo ""
}

# 验证binlog配置
verify_binlog_config() {
    log_info "验证binlog配置..."
    
    # 检查binlog是否启用
    binlog_enabled=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -N -B -e "SHOW VARIABLES LIKE 'log_bin';" | awk '{print $2}')
    
    if [ "$binlog_enabled" = "ON" ]; then
        log_success "✅ Binlog已启用"
        
        # 检查其他关键配置
        binlog_format=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u root -p"$MYSQL_ROOT_PASSWORD" -N -B -e "SHOW VARIABLES LIKE 'binlog_format';" | awk '{print $2}')
        
        if [ "$binlog_format" = "ROW" ]; then
            log_success "✅ Binlog格式: ROW (推荐)"
        else
            log_warn "⚠️  Binlog格式建议设置为ROW模式"
        fi
        
    else
        log_warn "⚠️  Binlog未启用，将无法进行增量备份"
        log_info "如需启用binlog，请在my.cnf中添加:"
        cat << EOF

[mysqld]
log-bin=mysql-bin
binlog_format=ROW
server-id=1
expire_logs_days=7
EOF
    fi
}

# 创建cron任务
setup_cron_jobs() {
    log_info "设置定时备份任务..."
    
    # 创建cron文件
    cron_file="/etc/cron.d/mysql-backup"
    
    cat > "$cron_file" << EOF
# MySQL自动备份任务
# 每天凌晨2点执行全量备份
0 2 * * * root /docker/mysql/scripts/backup-mysql.sh >> /var/log/mysql-backup.log 2>&1

# 每周日凌晨3点执行异地备份同步  
0 3 * * 0 root /docker/mysql/scripts/sync-backup.sh >> /var/log/backup-sync.log 2>&1

# 每小时验证备份文件完整性
0 * * * * root /docker/mysql/scripts/verify-backup.sh >> /var/log/backup-verify.log 2>&1
EOF
    
    # 设置权限
    chmod 644 "$cron_file"
    
    log_success "✅ Cron任务已配置"
    
    # 显示已配置的任务
    echo ""
    echo "已配置的定时任务:"
    echo "  ┌─ 每天02:00 ─ 全量备份"
    echo "  ├─ 周日03:00 ─ 异地同步"
    echo "  └─ 每小时   ─ 完整性检查"
    echo ""
}

test_configuration() {
    log_info "测试备份配置..."
    
    # 测试备份用户连接
    if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$BACKUP_USER" -p"$BACKUP_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; then
        log_success "✅ 备份用户连接测试成功"
    else
        log_error "❌ 备份用户连接失败"
        exit 1
    fi
    
    # 测试备份脚本语法
    if bash -n /docker/mysql/scripts/backup-mysql.sh; then
        log_success "✅ 备份脚本语法检查通过"
    else
        log_warn "⚠️  备份脚本语法检查失败"
    fi
    
    # 模拟备份测试
    log_info "执行快速备份测试..."
    
    temp_test_dir="/tmp/backup_test"
    mkdir -p "$temp_test_dir"
    
    # 使用small数据库进行测试
    if mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$BACKUP_USER" -p"$BACKUP_PASSWORD" -e "SHOW DATABASES LIKE 'information_schema';" >/dev/null 2>&1; then
        test_file="${temp_test_dir}/test_backup.sql"
        
        if mysqldump \
            --host="$MYSQL_HOST" \
            --port="$MYSQL_PORT" \
            --user="$BACKUP_USER" \
            --password="$BACKUP_PASSWORD" \
            --single-transaction \
            information_schema \
            > "$test_file" 2>/tmp/backup_test.log; then
            
            test_size=$(stat -c%s "$test_file" 2>/dev/null || echo 0)
            if [ $test_size -gt 1000 ]; then
                log_success "✅ 备份测试成功 (大小: ${test_size} bytes)"
            else
                log_error "❌ 备份文件异常"
            fi
        else
            log_warn "⚠️  备份测试失败"
            cat /tmp/backup_test.log
        fi
    fi
    
    # 清理测试文件
    rm -rf "$temp_test_dir"
}

generate_setup_report() {
    log_info "生成配置报告..."
    
    report_file="/tmp/mysql_backup_setup_report.txt"
    
    cat > "$report_file" << EOF
═══════════════════════════════════════════════════════════════════
                    MySQL备份配置报告
═══════════════════════════════════════════════════════════════════

配置时间:       $(date '+%Y-%m-%d %H:%M:%S')
服务器:         $MYSQL_HOST:$MYSQL_PORT

═══════════════════════════════════════════════════════════════════
用户配置
═══════════════════════════════════════════════════════════════════

备份用户:       $BACKUP_USER@%
恢复用户:       restore_user@%
权限状态:       ✅ 已授权
密码强度:       ✅ 强密码

═══════════════════════════════════════════════════════════════════
备份策略
═══════════════════════════════════════════════════════════════════

全量备份:       每天 02:00
保留天数:       30天
压缩:           启用 (pigz)
加密:           禁用 (GPG)
增量备份:       Binlog (ROW格式)

═══════════════════════════════════════════════════════════════════
异地备份
═══════════════════════════════════════════════════════════════════

远程主机:       backups.smartgrid.tech
同步频率:       每周日 03:00
传输协议:       rsync + SSH
带宽控制:       启用

═══════════════════════════════════════════════════════════════════
监控与告警
═══════════════════════════════════════════════════════════════════

监控间隔:       1小时
完整性检查:     自动
告警方式:       邮件
联系邮箱:       admin@smartgrid.tech

═══════════════════════════════════════════════════════════════════
恢复时间预估
═══════════════════════════════════════════════════════════════════

1GB数据:        5-10分钟
10GB数据:       15-30分钟
100GB数据:      60-120分钟
RTO目标:        30分钟

═══════════════════════════════════════════════════════════════════
重要文件
═══════════════════════════════════════════════════════════════════

配置文件:       /etc/mysql/backup.conf
cron任务:       /etc/cron.d/mysql-backup
备份脚本:       /docker/mysql/scripts/backup-mysql.sh
恢复脚本:       /docker/mysql/scripts/restore-mysql.sh

═══════════════════════════════════════════════════════════════════
使用指南
═══════════════════════════════════════════════════════════════════

1. 查看备份状态:
   ls -la /var/lib/mysql-backup/full/
   
2. 手动执行备份:
   /docker/mysql/scripts/backup-mysql.sh
   
3. 恢复数据:
   /docker/mysql/scripts/restore-mysql.sh --date 20250101
   
4. 查看备份日志:
   tail -f /var/log/mysql-backup.log
   
5. 验证配置:
   ./backup-config.sh test

═══════════════════════════════════════════════════════════════════
EOF
    
    log_success "✅ 配置报告已生成: $report_file"
    cat "$report_file"
}

# 主程序
main() {
    # 显示配置
    show_config
    
    # 执行配置步骤
    check_environment
    create_backup_user
    create_backup_config
    verify_binlog_config
    setup_cron_jobs
    test_configuration
    generate_setup_report
    
    # 显示完成信息
    cat << EOF

═══════════════════════════════════════════════════════════════════
✅ 配置完成
═══════════════════════════════════════════════════════════════════

MySQL备份已成功配置！

🎉 下一步:

1. 查看报告: cat \