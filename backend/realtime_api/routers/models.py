"""
智能电网负荷预测系统 - 模型管理API

提供:
- 模型训练跟踪
- 版本控制
- 性能监控
- 部署管理
- 快速回滚

author: 毕业设计项目
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse

from realtime_api.model_management import (
    ModelVersionManager,
    get_model_version_manager
)
from realtime_api.auth.dependencies import get_current_active_user
from realtime_api.schemas.auth import check_permission


# 创建路由器
router = APIRouter(prefix="/api/models", tags=["模型管理"])

# 日志配置
logger = logging.getLogger(__name__)


@router.post(
    "/train/experiment",
    status_code=status.HTTP_201_CREATED,
    description="记录训练实验"
)
@check_permission("model:train")
async def log_training_experiment(
    experiment_data: Dict[str, Any],
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_active_user)
):
    """记录训练实验"""
    try:
        manager = get_model_version_manager()
        
        # 提取数据
        model_type = experiment_data.get('model_type', 'Unknown')
        metrics = experiment_data.get('metrics', {})
        params = experiment_data.get('params', {})
        dataset_version = experiment_data.get('dataset_version')
        
        # 创建训练运行
        run_id = manager.start_training_run(
            model_type=model_type,
            dataset_version=dataset_version
        )
        
        # 后台任务记录详细数据
        background_tasks.add_task(
            log_experiment_details,
            run_id, model_type, metrics, params
        )
        
        logger.info(f"✅ 训练实验记录: {run_id} by {current_user.username}")
        
        return {
            "message": "训练实验记录成功",
            "run_id": run_id,
            "model_type": model_type
        }
        
    except Exception as e:
        logger.error(f"❌ 训练实验记录失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"实验记录失败: {str(e)}"
        )


@router.post(
    "/register/{run_id}",
    status_code=status.HTTP_201_CREATED,
    description="注册模型版本"
)
@check_permission("model:deploy")
async def register_model_version(
    run_id: str,
  ersion_description: Optional[str] = None,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_active_user)
):
    """注册模型到新版本"""
    try:
        manager = get_model_version_manager()
        
        # 构建模型URI
        model_uri = f"runs:/{run_id}/model"
        
        # 注册模型
        version = manager.register_model_version(
            run_id=run_id,
            model_uri=model_uri,
            version_description=version_description
        )
        
        # 后台任务: 验证模型质量
        background_tasks.add_task(
            verify_model_quality,
            manager.client, run_id, version
        )
        
        logger.info(f"✅ 模型注册: v{version} (用户: {current_user.username})")
        
        return {
            "message": "模型注册成功",
            "version": version,
            "run_id": run_id,
            "stage": "Staging"
        }
        
    except Exception as e:
        logger.error(f"❌ 模型注册失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"模型注册失败: {str(e)}"
        )


@router.post(
    "/deploy/{version}",
    status_code=status.HTTP_200_OK,
    description="部署模型到生产环境"
)
@check_permission("model:deploy")
async def deploy_model(
    version: str,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_active_user)
):
    """部署模型到生产环境"""
    try:
        manager = get_model_version_manager()
        
        # 转换到生产阶段
        success = manager.transition_model_stage(
            model_name="LoadForecast_Ensemble",
            version=version,
            stage="Production"
        )
        
        if success:
            # 后台任务: 更新应用模型
            background_tasks.add_task(
                update_production_model,
                manager, version
            )
            
            logger.info(f"✅ 模型部署: v{version} to Production (用户: {current_user.username})")
            
            return {
                "message": "模型部署成功",
                "version": version,
                "stage": "Production"
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="模型部署失败"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 模型部署异常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"模型部署失败: {str(e)}"
        )


@router.post(
    "/rollback/{target_version}",
    status_code=status.HTTP_200_OK,
    description="回滚到指定版本"
)
@check_permission("model:deploy")
async def rollback_model(
    target_version: str,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_active_user)
):
    """回滚模型到指定版本"""
    try:
        manager = get_model_version_manager()
        
        # 获取当前版本
        current_info = manager.get_production_model()
        
        # 执行回滚
        success = manager.rollback_model_version(target_version)
        
        if success:
            # 背景任务: 验证回滚
            background_tasks.add_task(
                validate_rollback,
                manager, current_info, target_version
            )
            
            logger.info(f"✅ 模型回滚: v{current_info['version'] if current_info else 'unknown'} -> v{target_version} (用户: {current_user.username})")
            
            return {
                "message": "模型回滚成功",
                "from_version": current_info['version'] if current_info else None,
                "to_version": target_version
            }
        else:
            raise HTTPException(
                status_code=400,
unk>detail="模型回滚失败"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 模型回滚异常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"模型回滚失败: {str(e)}"
        )


@router.get(
    "/production",
    description="获取生产环境模型信息"
)
@check_permission("model:read")
async def get_production_model_info(current_user=Depends(get_current_active_user)):
    """获取当前生产环境的模型信息"""
    try:
        manager = get_model_version_manager()
        model_info = manager.get_production_model()
        
        if model_info:
            logger.info(f"✅ 获取生产模型信息 (用户: {current_user.username})")
            
            return {
                "message": "生产模型信息",
                "model": model_info
            }
        else:
            return {
                "message": "生产环境暂无模型",
                "model": None
            }
            
    except Exception as e:
        logger.error(f"❌ 获取生产模型失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取生产模型失败: {str(e)}"
        )


@router.get(
    "/versions",
    description="获取所有模型版本"
)
@check_permission("model:read")
async def get_model_versions(
    stage: Optional[str] = None,
    limit: int = 10,
    current_user=Depends(get_current_active_user)
):
    """获取模型版本列表"""
    try:
        manager = get_model_version_manager()
        
        # 获取所有版本
        try:
            versions = manager.client.search_model_versions(
                f"name='LoadForecast_Ensemble'"
            )
        except Exception as search_e:
            logger.error(f"❌ 模型版本搜索失败: {search_e}")
            versions = []
        
        # 过滤阶段
        if stage:
            versions = [v for v in versions if v.current_stage == stage]
        
        # 限制数量
        versions = versions[:limit]
        
        # 格式化响应
        version_list = []
        for version in versions:
            version_list.append({
                "version": version.version,
                "stage": version.current_stage,
                "run_id": version.run_id,
                "creation_timestamp": version.creation_timestamp,
                "last_updated_timestamp": version.last_updated_timestamp,
                "status": version.status,
                "source": version.source
            })
        
        logger.info(f"✅ 获取模型版本 (用户: {current_user.username}) - {len(version_list)}个")
        
        return {
            "message": "模型版本列表",
            "count": len(version_list),
            "stage_filter": stage,
            "versions": version_list
        }
        
    except Exception as e:
        logger.error(f"❌ 获取模型版本失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取模型版本失败: {str(e)}"
        )


@router.get(
    "/performance/{version1}/compare/{version2}",
    description="比较两个模型版本性能"
)
@check_permission("model:read")
async def compare_model_versions(
    version1: str,
    version2: str,
    current_user=Depends(get_current_active_user)
):
    """比较两个模型版本的性能"""
    try:
        manager = get_model_version_manager()
        
        # 获取性能比较
        comparison_df = manager.compare_model_performance([version1, version2])
        
        if comparison_df.empty:
            return {
                "message": "无性能数据可比较",
                "comparison": {}
            }
        
        # 转换为JSON格式
        comparison_dict = comparison_df.to_dict(orient='records')
        
        # 计算比较结果
        analysis = analyze_model_comparison(comparison_dict)
        
        logger.info(f"✅ 模型性能比较: {version1} vs {version2} (用户: {current_user.username})")
        
        return {
            "message": "模型性能对比",
            "versions": [version1, version2],
            "comparison": comparison_dict,
            "analysis": analysis
        }
        
    except Exception as e:
        logger.error(f"❌ 模型比较失败: {e}")
ang>        raise HTTPException(
            status_code=500,
            detail=f"模型比较失败: {str(e)}"
        )


@router.get(
    "/deployment-history",
    description="获取模型部署历史"
)
@check_permission("model:read")
async def get_deployment_history(
    limit: int = 20,
    current_user=Depends(get_current_active_user)
):
    """获取模型部署历史"""
    try:
        manager = get_model_version_manager()
        
        # 获取部署历史
        history = manager.get_model_deployment_history()
        
        # 限制数量
        history = history[:limit]
        
        logger.info(f"✅ 获取部署历史 (用户: {current_user.username}) - {len(history)}条")
        
        return {
            "message": "模型部署历史",
            "count": len(history),
            "history": history
        }
        
    except Exception as e:
        logger.error(f"❌ 获取部署历史失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取部署历史失败: {str(e)}"
        )


@router.get(
    "/experiments",
    description="获取训练实验列表"
)
@check_permission("model:read")
async def get_training_experiments(
    limit: int = 20,
    current_user=Depends(get_current_active_user)
):
    """获取训练实验列表"""
    try:
        manager = get_model_version_manager()
        
        # 搜索运行
        try:
            runs = manager.client.search_runs(
                experiment_ids=[manager._get_experiment_id()],
                order_by=["start_time DESC"],
                max_results=limit
            )
        except Exception as search_e:
            logger.error(f"❌ 运行搜索失败: {search_e}")
            runs = []
        
        # 格式化为响应
        experiment_list = []
        for run in runs:
            # 提取标签
            model_type = None
            for tag_key, tag_value in run.data.tags.items():
                if tag_key == 'model_type':
                    model_type = tag_value
                    break
            
            experiment_list.append({
                "run_id": run.info.run_id,
                "experiment_id": run.info.experiment_id,
                "model_type": model_type or "Unknown",
                "start_time": run.info.start_time,
                "end_time": run.info.end_time,
                "status": run.info.status,
                "metrics": dict(run.data.metrics),
                "params": dict(run.data.params)
            })
        
        logger.info(f"✅ 获取训练实验 (用户: {current_user.username}) - {len(experiment_list)}个")
        
        return {
            "message": "训练实验列表",
            "count": len(experiment_list),
            "experiments": experiment_list
        }
        
    except Exception as e:
        logger.error(f"❌ 获取训练实验失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取训练实验失败: {str(e)}"
        )


@router.get(
    "/experiments/{run_id}",
    description="获取单条训练实验详情"
)
@check_permission("model:read")
async def get_experiment_details(
    run_id: str,
    current_user=Depends(get_current_active_user)
):
    """获取单个训练实验的详细信息"""
    try:
        manager = get_model_version_manager()
        
        # 获取运行详情
        try:
            run = manager.client.get_run(run_id)
        except Exception as get_e:
            logger.error(f"❌ 获取运行详情失败: {get_e}")
            raise HTTPException(
                status_code=404,
                detail=f"运行不存在: {run_id}"
            )
        
        # 构建响应
        experiment_data = {
            "run_id": run.info.run_id,
            "experiment_id": run.info.experiment_id,
            "start_time": run.info.start_time,
            "end_title": run.info.end_time,
            "status": run.info.status,
            "lifecycle_stage": run.info.lifecycle_stage,
            "artifact_uri": run.info.artifact_uri,
            "metrics": dict(run.data.metrics),
            "parameters": dict(run.data.params),
            "tags": dict(run.data.tags)
        }
        
        logger.info(f"✅ 获取实验详情: {run_id} (用户: {current_user.username})")
        
        return {
            "message": "训练实验详情",
            "experiment": experiment_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取实验详情异常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取实验详情失败: {str(e)}"
        )


@router.get(
    "/status",
    description="模型管理服务状态"
)
async def get_model_management_status():
    """检查模型管理服务状态"""
    try:
        manager = get_model_version_manager()
        
        # 测试基本服务
        experiment = manager.client.get_experiment_by_name(manager.experiment_name)
        
        # 检查生产模型
        production_model = manager.get_production_model()
        
        status_info = {
            "service": "model-management",
            "timestamp": datetime.now().isoformat(),
            "experiment_available": experiment is not None,
            "experiment_name": manager.experiment_name,
            "tracking_uri": manager.client.tracking_uri,
            "production_model": production_model,
            "health": "healthy"
        }
        
        logger.info("✅ 模型管理服务状态检查")
        return status_info
        
    except Exception as e:
        logger.error(f"❌ 模型管理服务状态异常: {e}")
        return {
            "service": "model-management",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "health": "unhealthy"
        }


# ============================================================================
# 后台任务函数
# ============================================================================

async def log_experiment_details(
    run_id: str,
    model_type: str,
    metrics: Dict[str, float],
    params: Dict[str, Any]
):
    """后台任务: 记录实验详细信息"""
    try:
        manager = get_model_version_manager()
        
        # 记录指标
        manager.log_training_metrics(run_id, metrics, model_type.lower())
        
        # 记录参数
        manager.log_model_parameters(run_id, params, model_type.lower())
        
        logger.info(f"✅ 实验详情已记录: {run_id}")
        
    except Exception as e:
        logger.error(f"❌ 记录实验详情失败: {e}")


async def verify_model_quality(
    client: Any,
    run_id: str,
    version: str
):
    """后台任务: 验证模型质量"""
    try:
        # 获取运行信息
        run = client.get_run(run_id)
        metrics = run.data.metrics
        
        # 质量检查
        issues = []
        recommendations = []
        
        # 检查RMSE
        if 'rmse' in metrics and metrics['rmse'] > 50.0:
            issues.append(f"RMSE过高: {metrics['rmse']:.2f}")
            recommendations.append("建议优化特征工程或模型参数")
        
        # 检查MAE
        if 'mae' in metrics and metrics['mae'] > 40.0:
            issues.append(f"MAE过高: {metrics['mae']:.2f}")
            recommendations.append("模型可能存在系统误差")
        
        # 记录质量报告
        quality_report = {
            "run_id": run_id,
            "version": version,
            "issues": issues,
            "recommendations": recommendations,
            "quality_score": calculate_quality_score(metrics)
        }
        
        logger.info(f"✅ 模型质量验证完成: {run_id} - 分数: {quality_report['quality_score']}")
        
    except Exception as e:
        logger.error(f"❌ 模型质量验证失败: {e}")


async def update_production_model(
    manager: ModelVersionManager,
    version: str
):
    """后台任务: 更新应用生产模型"""
    try:
        # 这里是伪代码示例, 实际需要根据应用架构实现  
        logger.info(f"📝 生产模型更新通知: v{version}")
        
        # TODO:
        # 1. 重启模型服务
        # 2. 清理缓存
        # 3. 更新配置
        # 4. 验证新模型功能
        
        logger.info(f"✅ 生产模型更新完成: v{version}")
        
    except Exception as e:
        logger.error(f"❌ 更新生产模型失败: {e}")


async def validate_rollback(
    manager: ModelVersionManager,
    current_info: Dict,
    target_version: str
):
    """后台任务: 验证回滚操作"""
    try:
        # 获取目标版本信息
        target_model = manager.get_production_model()
        
        # 验证基本属性
        validation_results = {
            "target_version": target_version,
            "is_loaded": target_model is not None,
            "current_stage": target_model['stage'] if target_model else None,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"✅ 回滚验证完成: {validation_results}")
        
    except Exception as e:
        logger.error(f"❌ 回滚验证失败: {e}")


# ============================================================================
# 辅助函数
# ============================================================================

def analyze_model_comparison(comparison_data: List[Dict]) -> Dict[str, Any]:
    """分析模型比较结果"""
    if len(comparison_data) != 2:
        return {"error": "需要2个版本数据"}
    
    model1, model2 = comparison_data
    
    analysis = {
        "summary": "",
        "rmse_winner": None,
        "mae_winner": None,
        "recommendation": ""
    }
    
    # 比较RMSE
    if 'rmse' in model1 and 'rmse' in model2:
        if model1['rmse'] < model2['rmse']:
            analysis['rmse_winner'] = model1['version']
            analysis['summary'] += f"版本{model1['version']}RMSE更优; "
        else:
            analysis['rmes_winner'] = model2['version']
            analysis['summary'] += f"版本{model2['version']}RMSE更优; "
    
    # 比较MAE
    if 'mae' in model1 and 'mae' in model2:
        if model1['mae'] < model2['mae']:
            analysis['mae_winner'] = model1['version']
            analysis['summary'] += f"版本{model1['version']}MAE更优; "
        else:
            analysis['mae_winner'] = model2['version']
            analysis['summary'] += f"版本{model2['version']}MAE更优; "
    
    # 给出建议
    if analysis['rmse_winner'] == analysis['mae_winner']:
        analysis['recommendation'] = f"建议部署版本{analysis['rmse_winner']}"
    else:
        analysis['recommendation'] = "需在RMSE和MAE间权衡选择"
    
   _analysis['summary'] = analysis['summary'][:-2]  # 移除最后一个分号
    
    return analysis


def calculate_quality_score(metrics: Dict[str, float]) -> float:
    """计算模型质量分数"""
    score = 100.0
    
    # RMSE扣分
    if 'rmse' in metrics:
        rmse = metrics['rmse']
        if rmse > 60.0:
            score -= 30
        elif rmse > 50.0:
            score -= 20
        elif rmse > 40.0:
            score -= 10
    
    # MAE扣分
    if 'mae' in metrics:
        mae = metrics['mae']
        if mae > 50.0:
            score -= 20
        elif mae > 40.0:
            score -= 10
        elif mae > 30.0:
            score -= 5
    
    return max(0.0, score)


# ============================================================================
# 路由汇总
# ============================================================================

__all__ = [
    'router'
]