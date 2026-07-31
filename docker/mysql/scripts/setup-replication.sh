#!/bin/bash
# MySQL主从复制自动设置脚本
# 由MySQL容器启动时自动执行

echo "=== MySQL Replication Setup Starting ==="

# 等待主库完全就绪
while ! mysql -h mysql-primary -u root -proot123 -e "SELECT 1;" > /dev/null 2>&1; do
  echo "[$(date)] 等待 MySQL 主库启动..."
  sleep 5
done

# 在主库上创建复制用户
echo "[$(date)] 在 master 上创建复制用户..."
mysql -h mysql-primary -u root -proot123 -e "
  CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED BY 'repl123' REQUIRE SSL;
  GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
  FLUSH PRIVILEGES;
"

# 获取主库状态
echo "[$(date)] 获取主库状态..."
MASTER_STATUS=$(mysql -h mysql-primary -u root -proot123 -e "SHOW MASTER STATUS\G")
MASTER_LOG_FILE=$(echo "$MASTER_STATUS" | grep "File:" | head -1 | awk '{print $2}')
MASTER_LOG_POS=$(echo "$MASTER_STATUS" | grep "Position:" | head -1 | awk '{print $2}')

echo "主库信息:"
echo "  日志文件: $MASTER_LOG_FILE"
echo "  位置: $MASTER_LOG_POS"

# 设置从库复制
echo "[$(date)] 配置 slave 的复制..."
mysql -u root -proot123 -e "
  STOP SLAVE;
  CHANGE MASTER TO
    MASTER_HOST='mysql-primary',
    MASTER_USER='repl',
    MASTER_PASSWORD='repl123',
    MASTER_LOG_FILE='$MASTER_LOG_FILE',
    MASTER_LOG_POS=$MASTER_LOG_POS,
    MASTER_SSL=1,
    GET_MASTER_PUBLIC_KEY=1;
  START SLAVE;
"

echo "[$(date)] 检查复制状态..."
mysql -u root -proot123 -e "SHOW SLAVE STATUS\G" | grep -E "(Slave_IO_Running|Slave_SQL_Running|Seconds_Behind_Master)"

echo "=== MySQL Replication Setup Complete ==="
