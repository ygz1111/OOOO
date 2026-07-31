#!/bin/bash
# MySQL实例初始化脚本
# 为每个实例设置唯一的 server-id

echo "=== MySQL Instance Initialization ==="

# 获取容器名称(包含实例编号)
CONTAINER_NAME=$(hostname)
echo "Container Name: $CONTAINER_NAME"

# 从容器名提取实例编号
if echo "$CONTAINER_NAME" | grep -q "replica"; then
    # 从 replica 名称中提取数字
    REPLICA_NUM=$(echo "$CONTAINER_NAME" | sed 's/.*\([0-9]*\).*/\1/' | sed 's/^$/1/')
    SERVER_ID=$((100 + REPLICA_NUM))  # replica-1 gets 101, replica-2 gets 102
    echo "Detected as replica. replica_instance=$REPLICA_NUM"
else
    # 默认为主库
    SERVER_ID=1
    echo "Detected as master. server_id=$SERVER_ID"
fi

# 更新配置文件中的server-id
echo "[$(date)] 设置 server-id=$SERVER_ID"
sed -i "s/server-id=2/server-id=$SERVER_ID/" /etc/mysql/conf.d/mysql.cnf

# 确保生成的server-id是唯一的
echo "最终的mysql.cnf内容:"
grep "server-id" /etc/mysql/conf.d/mysql.cnf || echo "未找到server-id配置"

echo "=== MySQL Instance Init Complete ==="

# 显示配置好的server-id
echo "最终的server-id设置为:"
grep "server-id" /etc/mysql/conf.d/mysql.cnf

# 保持容器运行
exec tail -f /dev/null
