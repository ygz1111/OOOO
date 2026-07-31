#!/usr/bin/env python3
"""
智能电网负荷预测系统 - 数据库使用示例

演示如何使用API查询历史数据

使用方法:
    python example_database_usage.py
"""

import requests
import json
import time
from datetime import datetime, timedelta


class DatabaseAPIClient:
    """数据库API客户端示例"""
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def get_prediction_history(
        self, 
        start_time: str = None, 
        end_time: str = None, 
        model_type: str = None, 
        limit: int = 10
    ):
        """获取历史负荷预测数据"""
        url = f"{self.base_url}/api/prediction/history"
        params = {}
        
        if start_time:
            params['start_time'] = start_time
        if end_time:
            params['end_time'] = end_time
        if model_type:
            params['model_type'] = model_type
        params['limit'] = limit
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_weather_history(
        self, 
        location: str = None, 
        hours: int = 24, 
        limit: int = 10
    ):
        """获取历史气象数据"""
        url = f"{self.base_url}/api/weather/history"
        params = {'hours': hours, 'limit': limit}
        
        if location:
            params['location'] = location
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_system_metrics(self, hours: int = 24, limit: int = 10):
        """获取系统监控指标"""
        url = f"{self.base_url}/api/system/metrics"
        params = {'hours': hours, 'limit': limit}
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def perform_load_prediction(self, target_date: str = "2026-07-25"):
        """执行负荷预测"""
        url = f"{self.base_url}/api/prediction/load"
        data = {
            "location": "Boston",
            "target_date": target_date,
            "hours_ahed": 24,
            "include_pv": True,
            "model_type": "ensemble"
        }
        
        response = self.session.post(url, json=data)
        response.raise_for_status()
        return response.json()


def print_section(title, content=None, indent=2):
    """打印带格式的章节"""
    print(f"\n{'#' * 60}")
    print(f"  {title}")
    print(f"{'#' * 60}")
    
    if content:
        if isinstance(content, dict) or isinstance(content, list):
            print(json.dumps(content, indent=indent, ensure_ascii=False))
        else:
            print(content)


def main():
    """主函数"""
    print("\n" + "█" * 60)
    print("    智能电网负荷预测系统 - 数据库使用示例")
    print("█" * 60)
    
    # 创建客户端
    client = DatabaseAPIClient()
    
    try:
        # 1. 首先执行一个负荷预测（这将生成数据）
        print_section("步骤1: 执行负荷预测")
        target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        print(f"正在对日期 {target_date} 执行24小时负荷预测...")
        prediction_result = client.perform_load_prediction(target_date)
        
        if prediction_result.get('status') == 'success':
            print(f"✅ 负荷预测成功完成")
            print(f"   预测结果数量: {len(prediction_result.get('predictions', []))} 条")
            print(f"   推理时间: {prediction_result.get('inference_time_ms', 'N/A')}ms")
            
            # 显示前3条预测结果
            print("\n   前3小时负荷预测:")
            for i, pred in enumerate(prediction_result.get('predictions', [])[:3]):
                print(f"     小时 {pred.get('hour', i)}: "
                      f"负荷={pred.get('load_forecast_mw', 0)}MW, "
                      f"光伏={pred.get('pv_estimation_mw', 0)}MW, "
                      f"净负荷={pred.get('net_load_mw', 0)}MW")
        else:
            print(f"❌ 负荷预测失败: {prediction_result.get('detail', '未知错误')}")
            return
        
        # 等待几秒确保数据已保存到数据库
        print("\n等待5秒以确保数据保存到数据库...")
        time.sleep(5)
        
        # 2. 查询历史负荷预测
        print_section("步骤2: 查询历史负荷预测数据")
        print("查询最近24小时的负荷预测数据...")
        
        history_result = client.get_prediction_history(limit=10)
        
        if history_result.get('success'):
            predictions = history_result.get('data', [])
            print(f"✅ 成功查询到 {len(predictions)} 条历史负荷预测")
            
            if predictions:
                print("\n   最新10条负荷预测记录:")
                for i, pred in enumerate(predictions[:10]):
                    print(f"     记录 {i+1}: ID={pred.get('id')}, "
                          f"预测负荷={pred.get('load_forecast_mw', 0)}MW, "
                          f"模型={pred.get('model_type', 'unknown')}, "
                          f"时间={pred.get('target_timestamp', 'N/A')}")
        else:
            print(f"❌ 查询失败: {history_result.get('message', '未知错误')}")
        
        # 3. 查询气象数据
        print_section("步骤3: 查询历史气象数据")
        print("查询Boston地区最近12小时的气象数据...")
        
        weather_result = client.get_weather_history(
            location="Boston", 
            hours=12, 
            limit=5
        )
        
        if weather_result.get('success'):
            weather_data = weather_result.get('data', [])
            print(f"✅ 成功查询到 {len(weather_data)} 条历史气象数据")
            
            if weather_data:
                print("\n   最新5条气象数据:")
                for i, data in enumerate(weather_data[:5]):
                    print(f"     记录 {i+1}: 时间={data.get('timestamp')}, "
                          f"温度={data.get('temperature_2m', 'N/A')}°C, "
                          f"湿度={data.get('relative_humidity_2m', 'N/A')}%",
                          f"风速={data.get('wind_speed_10m', 'N/A')}m/s")
        else:
            print(f"❌ 查询失败: {weather_result.get('message', '未知错误')}")
        
        # 4. 查询系统监控指标
        print_section("步骤4: 查询系统监控指标")
        print("查询最近12小时的系统监控数据...")
        
        metrics_result = client.get_system_metrics(hours=12, limit=5)
        
        if metrics_result.get('success'):
            metrics = metrics_result.get('data', [])
            print(f"✅ 成功查询到 {len(metrics)} 条系统监控指标")
            
            if metrics:
                print("\n   最新5条系统监控指标:")
                for i, metric in enumerate(metrics[:5]):
                    print(f"     记录 {i+1}: 时间={metric.get('timestamp')}, "
                          f"CPU={metric.get('cpu_percent', 'N/A')}%, "
                          f"内存={metric.get('memory_percent', 'N/A')}%",
                          f"GPU内存={metric.get('gpu_memory_used_mb', 'N/A')}MB")
        else:
            print(f"❌ 查询失败: {metrics_result.get('message', '未知错误')}")
        
        # 5. 总结
        print_section("总结")
        print("✅ 数据库功能验证完成！")
        print("\n🔍 可用的API端点:")
        print("   GET  /api/prediction/history      - 历史负荷预测查询")
        print("   GET  /api/weather/history         - 历史气象数据查询")
        print("   GET  /api/system/metrics          - 系统监控指标查询")
        print("   POST /api/prediction/load          - 执行负荷预测")
        print("   GET  /api/weather/current         - 获取当前气象数据")
        print("   GET  /api/system/status           - 获取系统状态")
        print("\n📖 API文档请访问: http://localhost:8000/docs")
        
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到API服务器")
        print("   请确保服务正在运行:")
        print("   python realtime_api/app.py")
    except requests.exceptions.HTTPError as e:
        print(f"❌ API请求失败: {e}")
    except KeyboardInterrupt:
        print("\n\n❌ 用户中断执行")
    except Exception as e:
        print(f"❌ 执行过程中出现异常: {e}")


if __name__ == "__main__":
    main()