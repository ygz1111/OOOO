#!/bin/bash
# ============================================================================
# 部署脚本 - 启动/停止/状态
# ============================================================================
set -e

cd "$(dirname "$0")/.."

case "${1:-up}" in

    up)
        echo "================================================"
        echo "  启动智能电网预测系统"
        echo "================================================"
        
        # 复制环境变量
        if [ ! -f .env ]; then
            echo "复制 .env.example → .env"
            cp docker/.env.example .env
        fi
        
        docker compose -f docker/docker-compose.yml --env-file .env up -d
        echo ""
        echo "✅ 服务已启动"
        echo "   API: http://localhost:${API_PORT:-8000}/docs"
        echo "   状态: docker compose -f docker/docker-compose.yml ps"
        ;;

    down)
        echo "停止服务..."
        docker compose -f docker/docker-compose.yml down
        echo "✅ 服务已停止"
        ;;

    restart)
        echo "重启服务..."
        docker compose -f docker/docker-compose.yml restart
        echo "✅ 服务已重启"
        ;;

    status)
        docker compose -f docker/docker-compose.yml ps
        echo ""
        echo "服务健康状态:"
        for svc in weather-collector feature-engine model-inference api-gateway; do
            status=$(docker inspect --format='{{.State.Health.Status}}' grid-predict-${svc//-/} 2>/dev/null || echo "not found")
            echo "  $svc: $status"
        done
        ;;

    logs)
        service="${2:-}"
        if [ -z "$service" ]; then
            docker compose -f docker/docker-compose.yml logs --tail=50
        else
            docker compose -f docker/docker-compose.yml logs --tail=50 "$service"
        fi
        ;;

    build)
        docker compose -f docker/docker-compose.yml build
        ;;

    clean)
        echo "清理容器和卷..."
        docker compose -f docker/docker-compose.yml down -v
        docker system prune -f
        echo "✅ 清理完成"
        ;;

    *)
        echo "用法: $0 {up|down|restart|status|logs|build|clean}"
        echo ""
        echo "  up       启动所有服务"
        echo "  down     停止所有服务"
        echo "  restart  重启所有服务"
        echo "  status   查看服务状态"
        echo "  logs [svc] 查看日志 (可选服务名)"
        echo "  build    重新构建镜像"
        echo "  clean    清理容器和卷"
        exit 1
        ;;
esac
