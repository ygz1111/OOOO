"""
智能电网负荷预测系统 - 模型版本管理

集成MLflow实现:
- 模型训练跟踪
- 参数版本化
- 性能监控
- 模型注册
- 部署管理
- 回滚机制

核心功能:
1. 训练过程记录 (参数、指标、工件)
2. 模型版本控制 (注册、标签、阶段)
3. 性能对比分析
4. 自动模型部署
5. 快速回滚恢复

作者: 毕业设计项目
"""

import os
import json
import time
import logging
import hashlib
import pickle
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

import numpy as np
import pandas as pd

import mlflow
from mlflow.tracking import MlflowClient
import mlflow.sklearn
import mlflow.pyfunc

from realtime_api.config import config_manager
from realtime_api.database import DatabaseManager

# 日志配置
logger = logging.getLogger(__name__)


class ModelVersionManager:
    """模型版本管理主类"""
    
    def __init__(self, tracking_uri: str = None):
        """
        初始化模型管理器
        
        Args:
            tracking_uri: MLflow跟踪URI, 默认从配置读取
        """
        # 从配置获取MLflow URI
        if tracking_uri is None:
            tracking_uri = os.environ.get('MLFLOW_TRACKING_URI', 'http://localhost:5000')
        
        # 设置MLflow
        mlflow.set_tracking_uri(tracking_uri)
        
        # 实验名称
        self.experiment_name = "smartgrid_load_forecasting"
        self._ensure_experiment_exists()
        
        # 模型名称
        self.base_model_name = "LoadForecast_Ensemble"
        
        # MLflow客户端
        self.client = MlflowClient(tracking_uri)
        
        # 数据库连接
        self.db_manager = DatabaseManager()
        
        logger.info(f"✅ 模型版本管理器初始化完成")
        logger.info(f"MLflow URI: {tracking_uri}")
        logger.info(f"实验: {self.experiment_name}")

    def _ensure_experiment_exists(self):
        """确保实验存在"""
        try:
            experiment = mlflow.get_experiment_by_name(self.experiment_name)
            if experiment is None:
                experiment_id = mlflow.create_experiment(
                    self.experiment_name,
                    artifact_location=None  # 使用默认位置
                )
                logger.info(f"✅ 创建实验: {self.experiment_name} (ID: {experiment_id})")
            else:
                logger.info(f"✅ 实验已存在: {self.experiment_name} (ID: {experiment.experiment_id})")
        except Exception as e:
            logger.error(f"❌ 实验处理失败: {e}")
            raise

    def start_training_run(
        self, 
        model_type: str,
        dataset_version: str = None,
        tags: Dict[str, str] = None
    ) -> str:
        """
        开始新的训练运行
        
        Args:
            model_type: 模型类型 (LSTM, BiGRU, TCN, Transformer)
            dataset_version: 数据集版本
            tags: 自定义标签
            
        Returns:
            运行ID
        """
        try:
            # 设置实验
            mlflow.set_experiment(self.experiment_name)
            
            # 构建默认标签
            default_tags = {
                'project': 'smartgrid-load-forecasting',
                'model_type': model_type,
                'source': 'production',
                'experiment': 'ensemble-optimization',
                'dataset_version': dataset_version or 'v1.0',
                'environment': 'production',
                'created_by': 'system'
            }
            
            # 合并用户标签
            if tags:
                default_tags.update(tags)
            
            # 创建运行
            with mlflow.start_run() as run:
                # 设置标签
                mlflow.set_tags(default_tags)
                
                # 记录运行信息
                mlflow.log_param("start_time", datetime.now().isoformat())
                mlflow.log_param("model_type", model_type)
                
                logger.info(f"✅ 开始训练运行: {run.info.run_id} - {model_type}")
                
                return run.info.run_id
                
        except Exception as e:
            logger.error(f"❌ 训练运行创建失败: {e}")
            raise

    def log_training_metrics(
        self,
        run_id: str,
        metrics: Dict[str, float],
        prefix: str = None
    ):
        """
        记录训练指标
        
        Args:
            run_id: 运行ID
            metrics: 指标字典
            prefix: 指标前缀
        """
        try:
            # 设置运行上下文
            with mlflow.start_run(run_id=run_id):
                
                # 记录指标
                for key, value in metrics.items():
                    metric_key = f"{prefix}.{key}" if prefix else key
                    mlflow.log_metric(metric_key, value)
                    
                logger.info(f"✅ 记录指标: {run_id} - {len(metrics)}项")
                
        except Exception as e:
            logger.error(f"❌ 指标记录失败: {e}")
            raise

    def log_model_parameters(
        self,
        run_id: str,
        params: Dict[str, Any],
        prefix: str = None
    ):
        """
        记录模型参数
        
        Args:
            run_id: 运行ID
            params: 参数字典
            prefix: 参数前缀
        """
        try:
            # 设置运行上下文
            with mlflow.start_run(run_id=run_id):
                
                # 记录参数
                for key, value in params.items():
                    param_key = f"{prefix}.{key}" if prefix else key
                    
                    # 处理复杂对象
                    if isinstance(value, (dict, list)):
                        mlflow.log_text(json.dumps(value, indent=2), f"{param_key}.json")
                    elif isinstance(value, (np.ndarray, pd.DataFrame)):
                        with open(f"/tmp/{key}.pkl", "wb") as f:
                            pickle.dump(value, f)
                        mlflow.log_artifact(f"/tmp/{key}.pkl", "parameters")
                        os.remove(f"/tmp/{key}.pkl")
                    else:
                        try:
                            mlflow.log_param(param_key, str(value))
                        except Exception as param_e:
                            logger.warning(f"❌ 参数记录失败 {param_key}: {param_e}")
                            mlflow.log_text(str(value), f"{param_key}.txt")
                
                logger.info(f"✅ 记录参数: {run_id} - {len(params)}项")
                
        except Exception as e:
            logger.error(f"❌ 参数记录失败: {e}")
            raise

    def log_model_artifacts(
        self,
        run_id: str,
        artifacts: Dict[str, str],
        artifact_path: str = "artifacts"
    ):
        """
        记录模型工件
        
        Args:
            run_id: 运行ID
            artifacts: 工件字典 {name: path}
            artifact_path: 工件路径
        """
        try:
            # 设置运行上下文
            with mlflow.start_run(run_id=run_id):
                
                # 记录工件
                for name, path in artifacts.items():
                    if os.path.exists(path):
                        mlflow.log_artifact(path, artifact_path)
                        logger.info(f"✅ 记录工件: {name} -> {path}")
                    else:
                        logger.warning(f"⚠️ 工件文件不存在: {path}")
                
        except Exception as e:
            logger.error(f"❌ 工件记录失败: {e}")
            raise

    def save_trained_model(
        self,
        run_id: str,
        model,
        model_signature: Any = None,
        input_example: Any = None
    ) -> str:
        """
        保存训练好的模型
        
        Args:
            run_id: 运行ID
            model: 模型对象
            model_signature: 模型签名
            input_example: 输入示例
            
        Returns:
            模型URI
        """
        try:
            model_name = f"{self.base_model_name}_{run_id}"
            
            # 设置运行上下文
            with mlflow.start_run(run_id=run_id):
                
                # 保存模型
                if hasattr(model, 'predict') and hasattr(model, 'fit'):
                    # scikit-learn风格模型
                    mlflow.sklearn.log_model(
                        sk_model=model.copy(),
                        artifact_path="model",
                        signature=model_signature,
                        input_example=input_example
                    )
                else:
                    # 自定义模型 (保存为pyfunc)
                    custom_model = CustomSklearnModel(model)
                    mlflow.pyfunc.log_model(
                        artifact_path="model",
                        python_model=custom_model,
                        signature=model_signature,
                        input_example=input_example
                    )
                
                logger.info(f"✅ 模型保存完成: {model_name}")
                
                # 返回模型URI
                model_uri = f"runs:/{run_id}/model"
                return model_uri
                
        except Exception as e:
            logger.error(f"❌ 模型保存失败: {e}")
            raise

    def register_model_version(
        self,
        run_id: str,
        model_uri: str,
        version_description: str = None,
        stage: str = "Staging"
    ) -> str:
        """
        注册模型版本
        
        Args:
            run_id: 运行ID
            model_uri: 模型URI
            version_description: 版本描述
            stage: 部署阶段
            
        Returns:
            版本号
        """
        try:
            model_name = self.base_model_name
            
            # 注册模型
            result = mlflow.register_model(
                model_uri=model_uri,
                name=model_name,
                tags={
                    'run_id': run_id,
                    'registered_at': datetime.now().isoformat(),
                    'registered_by': 'system',
                    'description': version_description or f"Version from run {run_id}"
                }
            )
            
            # 转换为指定阶段
            if stage != "Staging":
                self.transition_model_stage(
                    result.name,
                    result.version,
                    stage
                )
            
            logger.info(f"✅ 模型注册成功: {result.name} v{result.version}")
            return result.version
            
        except Exception as e:
            logger.error(f"❌ 模型注册失败: {e}")
            raise

    def transition_model_stage(
        self, model_name: str, version: str, stage: str) -> bool:
        """
        转换模型部署阶段
        
        Args:
            model_name: 模型名称
            version: 版本号
            stage: 目标阶段 (Staging, Production, Archived)
            
        Returns:
            是否成功
        """
        try:
            # 获取当前阶段
            versions = self.client.get_model_version(
                name=model_name, 
                version=str(version)
            )
            
            current_stage = versions.current_stage
            
            if current_stage == stage:
                logger.info(f"✅ 模型已在目标阶段: {model_name} v{version} -> {stage}")
                return True
            
            # 转换阶段
            self.client.transition_model_version_stage(
                name=model_name,
                version=str(version),
                stage=stage,
                archive_existing_versions=True  # 归档现有版本
            )
            
            logger.info(f"✅ 模型阶段转换: {model_name} v{version}: {current_stage} -> {stage}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 模型阶段转换失败: {e}")
            return False

    def get_production_model(self) -> Optional[Dict[str, Any]]:
        """
        获取生产环境模型信息
        
        Returns:
            生产模型信息
        """
        try:
            # 获取生产版本
            versions = self.client.get_latest_versions(
                self.base_model_name,
                stages=["Production"]
            )
            
            if not versions:
                logger.warning(f"⚠️  生产环境无模型: {self.base_model_name}")
                return None
            
            prod_version = versions[0]
            
            model_info = {
                'name': prod_version.name,
                'version': prod_version.version,
                'stage': prod_version.current_stage,
                'run_id': prod_version.run_id,
                'creation_timestamp': prod_version.creation_timestamp,
                'last_updated_timestamp': prod_version.last_updated_timestamp,
                'source': prod_version.source,
                'status': prod_version.status
            }
            
            logger.info(f"✅ 获取生产模型: {prod_version.name} v{prod_version.version}")
            return model_info
            
        except Exception as e:
            logger.error(f"❌ 获取生产模型失败: {e}")
            return None

    def load_production_model(self) -> Optional[Any]:
        """
        加载生产环境模型
        
        Returns:
            模型对象
        """
        try:
            model_info = self.get_production_model()
            if not model_info:
                return None
            
            # 构建模型URI
            model_uri = f"models:/{model_info['name']}/{model_info['stage']}"
            
            # 加载模型
            model = mlflow.pyfunc.load_model(model_uri)
            
            logger.info(f"✅ 生产模型加载成功: {model_info['name']} v{model_info['version']}")
            return model
            
        except Exception as e:
            logger.error(f"❌ 生产模型加载失败: {e}")
            return None

    def rollback_model_version(self, target_version: str) -> bool:
        """
        回滚到指定版本
        
        Args:
            target_version: 目标版本号
            
        Returns:
            是否成功
        """
        try:
            model_name = self.base_model_name
            
            # 获取目标版本
            try:
                version = self.client.get_model_version(model_name, str(target_version))
            except Exception:
                logger.error(f"❌ 找不到版本: v{target_version}")
                return False
            
            # 转换为生产环境
            success = self.transition_model_stage(
                model_name,
                target_version,
                "Production"
            )
            
            if success:
                # 记录回滚操作
                self._log_model_operation(
                    operation="rollback",
                    model_name=model_name,
                    from_version=None,
                    to_version=target_version,
                    reason="回滚操作",
                    success=True
                )
                
                logger.info(f"✅ 模型回滚成功: -> v{target_version}")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"❌ 模型回滚失败: {e}")
            
            # 记录失败操作
            self._log_model_operation(
                operation="rollback",
                model_name=self.base_model_name,
                from_version=None,
                to_version=target_version,
                reason=f"回滚失败: {e}",
                success=False
            )
            
            return False

    def compare_model_performance(
        self, versions: List[str]) -> pd.DataFrame:
        """
        比较多个模型性能
        
        Args:
            versions: 版本列表
            
        Returns:
            性能比较DataFrame
        """
        try:
            results = []
            
            for version in versions:
                try:
                    # 获取版本信息
                    mversion = self.client.get_model_version(
                        self.base_model_name,
                        str(version)
                    )
                    
                    # 获取运行信息
                    run = self.client.get_run(mversion.run_id)
                    
                    # 提取指标
                    metrics = run.data.metrics
                    
                    # 构建记录
                    record = {
                        'version': version,
                        'stage': mversion.current_stage,
                        'created_at': datetime.fromtimestamp(
                            mversion.creation_timestamp / 1000
                        ),
                        'status': mversion.status,
                    }
                    
                    # 添加指标
                    for key, value in metrics.items():
                        if isinstance(value, (int, float)):
                            record[key] = float(value)
                    
                    results.append(record)
                    
                except Exception as e:
                    logger.error(f"❌ 获取版本{version}信息失败: {e}")
                    continue
            
            # 转换为DataFrame
            df = pd.DataFrame(results)
            
            # 计算排名
            if not df.empty and 'rmse' in df.columns:
                df['rmse_rank'] = df['rmse'].rank(method='min')
            
            if not df.empty and 'mae' in df.columns:
                df['mae_rank'] = df['mae'].rank(method='min')
            
            logger.info(f"✅ 模型比较完成: {len(versions)}个版本")
            return df
            
        except Exception as e:
            logger.error(f"❌ 模型比较失败: {e}")
            return pd.DataFrame()

    def get_model_deployment_history(self) -> List[Dict[str, Any]]:
        """
        获取模型部署历史
        
        Returns:
            部署历史列表
        """
        try:
            operation_logs = self._get_model_operations()
            
            # 过滤部署和回滚操作
            deployment_logs = []
            
            for log in operation_logs:
                if log['operation'] in ['deploy', 'rollback', 'stage_transition']:
                    deployment_logs.append(log)
            
            # 按时间排序 (最新的在前)
            deployment_logs.sort(
                key=lambda x: x['timestamp'],
                reverse=True
            )
            
            logger.info(f"✅ 获取部署历史: {len(deployment_logs)}条记录")
            return deployment_logs
            
        except Exception as e:
            logger.error(f"❌ 获取部署历史失败: {e}")
            return []

    def _log_model_operation(
        self,
        operation: str,
        model_name: str,
        from_version: Optional[str],
        to_version: str,
        reason: str,
        success: bool
    ):
        """记录模型操作"""
        try:
            # 记录到数据库
            operation_log = {
                'operation': operation,
                'model_name': model_name,
                'from_version': from_version,
                'to_version': to_version,
                'reason': reason,
                'success': success,
                'timestamp': int(time.time()),
                'performed_by': 'system'
            }
            
            # TODO: 保存到数据库的operation_logs表
            # 这里只是记录日志, 实际需要保存到数据库
            
            logger.info(f"📝 模型操作记录: {operation} {model_name} {from_version} -> {to_version}")
            
        except Exception as e:
            logger.error(f"❌ 操作记录失败: {e}")

    def _get_model_operations(self) -> List[Dict[str, Any]]:
        """获取模型操作记录"""
        # TODO: 从数据库查询
        # 这里是模拟数据
        return [
            {
                'operation': 'deploy',
                'model_name': self.base_model_name,
                'from_version': None,
                'to_version': '1',
                'reason': '首次部署',
                'success': True,
                'timestamp': 1704067200
            }
        ]


class CustomSklearnModel(mlflow.pyfunc.PythonModel):
    """自定义sklearn模型包装类"""
    
    def __init__(self, model):
        self.model = model
        
    def predict(self, context, model_input):
        """预测方法"""
        return self.model.predict(model_input)


# ============================================================================
# 便捷的工具函数
# ============================================================================

def get_model_version_manager() -> ModelVersionManager:
    """获取模型版本管理器实例"""
    tracking_uri = config_manager.get_config_value('mlflow', 'tracking_uri', 'http://localhost:5000')
    return ModelVersionManager(tracking_uri)

def log_training_experiment(
    run_id: str,
    model_type: str,
    metrics: Dict[str, float],
    params: Dict[str, Any]
) -> bool:
    """
    记录训练实验 (便捷函数)
    
    Args:
        run_id: 运行ID
        model_type: 模型类型
        metrics: 指标
        params: 参数
        
    Returns:
        是否成功
    """
    try:
        manager = get_model_version_manager()
        
        # 记录指标
        manager.log_training_metrics(run_id, metrics, model_type.lower())
        
        # 记录参数
        manager.log_model_parameters(run_id, params, model_type.lower())
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 训练实验记录失败: {e}")
        return False

def register_new_model_version(
    run_id: str,
    model_uri: str
ousse