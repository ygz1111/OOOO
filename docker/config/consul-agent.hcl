# Consul Agent 配置
# 用于服务注册和发现
datacenter = "grid-dc"
data_dir = "/consul/data"

log_level = "INFO"

# 服务器模式 (仅服务器节点设置 server = true)
server = false

# 连接到 Consul 服务器集群
retry_join = ["consul-server-1", "consul-server-2", "consul-server-3"]

# 客户端绑定地址
bind_addr = "0.0.0.0"

# HTTP API 监听地址
ports = {
  http = 8500
  dns  = 8600
}

# 服务定义
service = {
  name = "grid-service"
  port = 8000

  # 健康检查
  check = {
    http     = "http://localhost:8000/api/system/status"
    interval = "10s"
    timeout  = "5s"
  }
}

# 性能调优
telemetry = {
  dogstatsd_addr = "localhost:8125"
  disable_hostname = true
}