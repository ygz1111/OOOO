#!/bin/bash
# 模型推理服务入口脚本
set -e

echo "================================================"
echo "  Model Inference Service"
echo "================================================"
echo "  MODEL_DIR: ${MODEL_DIR:-/app/outputs}"
echo "  DEVICE: ${DEVICE:-cpu}"
echo "================================================"

echo "启动模型推理服务..."
exec "$@"
