#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 性能基准测试

用于对比优化前后的性能差异
"""

import asyncio
import time
import json
import statistics
import psutil
import numpy as np
from datetime import datetime
from typing import Dict, List, Any
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
import matplotlib.pyplot as plt
from dataclasses import dataclass

@dataclass
class BenchmarkConfig:
    """基准测试配置"""
    base_url: str = "http://localhost:8000"
    num_requests: int = 100
    concurrency_levels: List[int] = None
    timeout: float = 30.0
    warmup_requests: int = 10
    
    def __post_init__(self):
        if self.concurrency_levels is None:
            self.concurrency_levels = [5, 10, 15, 20]

class PerformanceBenchmark:
    """综合性能基准测试"""
    
    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.results = {}
        self.test_data = self._generate_test_data()
        
    def _generate_test_data(self):
        """生成测试数据"""
        return {
            "weather_data": [
                {
                    "timestamp": "2024-01-15T12:00:00Z",
                    "location": "Boston",
                    "temperature_2m": 25.5,
                    "dew_point_2m": 15.2,
                    "relative_humidity_2m": 65.0,
                    "wind_speed_10m": 8.5,
                    "cloud_cover": 30,
                    "shortwave_radiation": 800,
                }
            ] * 24
        }
    
    async def run_comprehensive_benchmark(self):
        """运行全面性能基准测试"""
        print("🚀 开始性能基准测试...")
        
        try:
            # 预热系统
            await self._warmup_system()
            
            # 运行时间测试
            print("\n📈 运行时间测试...")
            response_times = await self._test_response_times()
            
            # 运行并发测试
            print("\n🔄 并发能力测试...")
            concurrency_results = await self._test_concurrent_performance()
            
            # 运行内存测试
            print("\n💾 内存使用测试...")
            memory_results = await self._test_memory_usage()
            
            # 运行缓存测试
            print("\n🎯 缓存效果测试...")
            cache_results = await self._test_cache_effectiveness()
            
            # 运行批处理测试
            print("\n📊 批处理性能...")
            batch_results = await self._test_batch_performance()
            
            # 汇总结果
            benchmark_results = {
                "timestamp": datetime.now().isoformat(),
                "test_config": self.config.__dict__,
                "response_times": response_times,
                "concurrency": concurrency_results,
                "memory_usage": memory_results,
                "cache_performance": cache_results,
                "batch_performance": batch_results,
                "summary": self._generate_summary(
                    response_times, concurrency_results, 
                    memory_results, cache_results, batch_results
                )
            }
            
            # 保存结果
            self._save_results(benchmark_results)
            
            # 生成性能报告
            self._generate_performance_report(benchmark_results)
            
            return benchmark_results
            
        except Exception as e:
            print(f"❌ 基准测试失败: {str(e)}")
            raise
    
    async def _warmup_system(self):
        """系统预热"""
        print(f"🔥 系统预热 ({self.config.warmup_requests} 请求)...")
        
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout
        ) as client:
            
            for i in range(self.config.warmup_requests):
                try:
                    await client.post("/api/prediction/load", json=self.test_data)
                except Exception as e:
                    print(f"预热请求 {i+1} 错误: {e}")
                
                if (i + 1) % 5 == 0:
                    print(f"  已发送 {i+1}/{self.config.warmup_requests} 预热请求")
    
    async def _test_response_times(self):
        """响应时间测试"""
        response_times_ms = []
        success_count = 0
        error_count = 0
        
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout
        ) as client:
            
            # 准备请求任务
            tasks = []
            for _ in range(self.config.num_requests):
                task = self._make_single_request(client)
                tasks.append(task)
            
            print(f"📤 发送 {len(tasks)} 个请求...")
            
            # 并发执行所有请求
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for i, result in enumerate(results):
                if isinstance(result, tuple) and len(result) == 3:
                    response_time, success, _ = result
                    response_times_ms.append(response_time)
                    
                    if success:
                        success_count += 1
                    else:
                        error_count += 1
                else:
                    error_count += 1
                    print(f"请求 {i+1} 异常: {result}")
        
        # 计算统计指标
        if response_times_ms:
            stats = {
                "total_requests": len(response_times_ms),
                "successful_requests": success_count,
                "failed_requests": error_count,
                "success_rate": success_count / len(response_times_ms),
                "mean_ms": statistics.mean(response_times_ms),
                "median_ms": statistics.median(response_times_ms),
                "min_ms": min(response_times_ms),
                "max_ms": max(response_times_ms),
                "std_ms": statistics.stdev(response_times_ms) if len(response_times_ms) > 1 else 0,
                "p95_ms": np.percentile(response_times_ms, 95),
                "p99_ms": np.percentile(response_times_ms, 99),
            }
            
            print(f"✅ 响应时间测试完成:")
            print(f"   平均: {stats['mean_ms']:.2f}ms")
            print(f"   P95: {stats['p95_ms']:.2f}ms")
            print(f"   P99: {stats['p99_ms']:.2f}ms")
            print(f"   成功率: {stats['success_rate']:.1%}")
            
            return stats
        else:
            print("❌ 没有有效的响应时间数据")
            return {}
    
    async def _make_single_request(self, client):
        """发送单个请求并测量时间"""
        start_time = time.perf_counter()
        
        try:
            response = await client.post("/api/prediction/load", json=self.test_data)
            end_time = time.perf_counter()
            
            response_time_ms = (end_time - start_time) * 1000
            success = response.status_code == 200
            
            return response_time_ms, success, response
            
        except Exception as e:
            end_time = time.perf_counter()
            response_time_ms = (end_time - start_time) * 1000
            
            return response_time_ms, False, str(e)
    
    async def _test_concurrent_performance(self):
        """并发性能测试"""
        concurrency_results = {}
        
        for concurrency_level in self.config.concurrency_levels:
            print(f"   测试 {concurrency_level} 并发...")
            
            # 运行时间更长的并发测试
            test_duration = 60  # 60秒
            results = await self._run_concurrent_test(
                concurrency_level, test_duration
            )
            
            concurrency_results[concurrency_level] = results
            
            print(f"     成功率: {results['success_rate']:.1%}")
            print(f"     平均响应时间: {results['avg_response_time_ms']:.2f}ms")
            print(f"     总请求数: {results['total_requests']}")
        
        return concurrency_results
    
    async def _run_concurrent_test(self, concurrency_level, duration_seconds):
        """运行特定并发级别的测试"""
        start_time = time.time()
        request_count = 0
        success_count = 0
        response_times = []
        
        # 创建并发任务
        semaphore = asyncio.Semaphore(concurrency_level)
        
        async def controlled_request():
            async with semaphore:
                nonlocal request_count, success_count
                
                response_time, success, _ = await self._make_single_request(
                    httpx.AsyncClient(base_url=self.config.base_url, timeout=self.config.timeout)
                )
                
                request_count += 1
                response_times.append(response_time)
                
                if success:
                    success_count += 1
        
        # 持续发送请求
        while time.time() - start_time < duration_seconds:
            # 同时启动多个请求
            tasks = [controlled_request() for _ in range(concurrency_level)]
            
            # 等待这批请求完成或超时
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                pass  # 某些请求超时是正常的
            
            # 小延迟避免过于激进
            await asyncio.sleep(0.1)
        
        # 计算结果
        if response_times:
            return {
                "concurrency_level": concurrency_level,
                "test_duration_seconds": duration_seconds,
                "total_requests": request_count,
                "successful_requests": success_count,
                "success_rate": success_count / request_count if request_count > 0 else 0,
                "avg_response_time_ms": statistics.mean(response_times),
                "median_response_time_ms": statistics.median(response_times),
                "min_response_time_ms": min(response_times),
                "max_response_time_ms": max(response_times),
                "throughput_rps": request_count / duration_seconds,
            }
        else:
            return {
                "concurrency_level": concurrency_level,
                "test_duration_seconds": duration_seconds,
                "total_requests": 0,
                "successful_requests": 0,
                "success_rate": 0,
                "avg_response_time_ms": 0,
                "throughput_rps": 0,
            }
    
    async def _test_memory_usage(self):
        """内存使用测试"""
        print("   监控内存使用...")
        
        # 获取初始内存使用
        initial_memory = psutil.virtual_memory().percent
        initial_process_memory = psutil.Process().memory_info().rss / 1024**3
        
        # 模拟负载期间
        memory_samples = []
        process_memory_samples = []
        
        async def monitor_memory():
            for _ in range(60):  # 监控60秒
                memory_percent = psutil.virtual_memory().percent
                process_memory_gb = psutil.Process().memory_info().rss / 1024**3
                
                memory_samples.append(memory_percent)
                process_memory_samples.append(process_memory_gb)
                
                await asyncio.sleep(1)
        
        # 在内存监控期间运行一些请求
        tasks = [
            monitor_memory(),
            asyncio.create_task(self._run_light_load())
        ]
        
        await asyncio.gather(*tasks)
        
        if memory_samples and process_memory_samples:
            return {
                "initial_memory_percent": initial_memory,
                "initial_process_memory_gb": initial_process_memory,
                "avg_memory_percent": statistics.mean(memory_samples),
                "max_memory_percent": max(memory_samples),
                "min_memory_percent": min(memory_samples),
                "avg_process_memory_gb": statistics.mean(process_memory_samples),
                "peak_process_memory_gb": max(process_memory_samples),
                "memory_growth_percent": statistics.mean(memory_samples) - initial_memory,
                "memory_growth_gb": max(process_memory_samples) - initial_process_memory,
            }
        else:
            return {}
    
    async def _run_light_load(self):
        """运行轻量级负载用于内存测试"""
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout
        ) as client:
            
            for _ in range(30):  # 30个请求
                try:
                    await client.post("/api/prediction/load", json=self.test_data)
                except Exception:
                    pass  # 忽略错误，重点是内存监控
                
                await asyncio.sleep(0.5)
    
    async def _test_cache_effectiveness(self):
        """缓存效果测试"""
        print("   测试缓存性能...")
        
        # 发送相同的请求来测试缓存命中率
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout
        ) as client:
            
            results = []
            
            # 第一次请求 (应该缓存未命中)
            start_time = time.perf_counter()
            response = await client.post("/api/prediction/load", json=self.test_data)
            first_request_time = (time.perf_counter() - start_time) * 1000
            
            # 立即发送相同请求 (应该缓存命中)
            cache_hit_times = []
            for i in range(10):
                start_time = time.perf_counter()
                response = await client.post("/api/prediction/load", json=self.test_data)
                cache_hit_time = (time.perf_counter() - start_time) * 1000
                cache_hit_times.append(cache_hit_time)
                
                if response.status_code == 200 and response.json().get('cache_hit'):
                    results.append('hit')
                else:
                    results.append('miss')
            
            # 计算结果
            hit_count = results.count('hit')
            miss_count = results.count('miss')
            
            return {
                "first_request_time_ms": first_request_time,
                "cache_hit_times_ms": cache_hit_times,
                "avg_cache_hit_time_ms": statistics.mean(cache_hit_times),
                "min_cache_hit_time_ms": min(cache_hit_times),
                "max_cache_hit_time_ms": max(cache_hit_times),
                "hit_count": hit_count,
                "miss_count": miss_count,
                "hit_ratio": hit_count / len(results) if results else 0,
                "speedup_factor": first_request_time / statistics.mean(cache_hit_times) if cache_hit_times and statistics.mean(cache_hit_times) > 0 else 1,
            }
    
    async def _test_batch_performance(self):
        """批处理性能测试"""
        print("   测试批处理性能...")
        
        # 测试不同批量大小的性能
        batch_sizes = [5, 10, 20, 50]
        batch_results = {}
        
        for batch_size in batch_sizes:
            # 创建批量请求
            requests = [self.test_data for _ in range(batch_size)]
            
            start_time = time.perf_counter()
            
            async with httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout * 2  # 批处理需要更多时间
            ) as client:
                
                try:
                    response = await client.post("/api/prediction/batch", json={
                        "requests": requests
                    })
                    
                    total_time = (time.perf_counter() - start_time) * 1000
                    
                    if response.status_code == 200:
                        result_data = response.json()
                        successful_requests = result_data.get('successful_requests', 0)
                        
                        batch_results[batch_size] = {
                            "batch_size": batch_size,
                            "total_time_ms": total_time,
                            "successful_requests": successful_requests,
                            "failures": batch_size - successful_requests,
                            "avg_per_request_ms": total_time / batch_size,
                            "throughput_rps": (successful_requests / (total_time / 1000)) if total_time > 0 else 0
                        }
                    else:
                        batch_results[batch_size] = {
                            "batch_size": batch_size,
                            "error": f"HTTP {response.status_code}",
                            "total_time_ms": total_time
                        }
                        
                except Exception as e:
                    batch_results[batch_size] = {
                        "batch_size": batch_size,
                        "error": str(e),
                        "total_time_ms": (time.perf_counter() - start_time) * 1000
                    }
            
            # 小延迟
            await asyncio.sleep(1)
        
        return batch_results
    
    def _generate_summary(self, response_times, concurrency, memory, cache, batch):
        """生成性能摘要"""
        summary = {
            "timestamp": datetime.now().isoformat(),
            "overall_score": 0,  # 计算综合性能得分
            "key_improvements": [],
            "performance_grade": "",
            "recommendations": []
        }
        
        # 计算响应时间得分 (0-100)
        if response_times and response_times.get('mean_ms'):
            mean_response = response_times['mean_ms']
            if mean_response < 10000:  # 10秒以内
                response_score = 100
            elif mean_response < 15000:  # 15秒以内  
                response_score = 80
            elif mean_response < 30000:  # 30秒以内
                response_score = 60
            else:
                response_score = 40
            
            summary['key_improvements'].append(
                f"平均响应时间: {mean_response:.1f}ms"
            )
        else:
            response_score = 0
        
        # 计算并发能力得分
        max_concurrent = 0
        if concurrency:
            for level, results in concurrency.items():
                if results.get('success_rate', 0) > 0.8:  # 80%成功率
                    max_concurrent = max(max_concurrent, level)
        
        if max_concurrent >= 15:
            concurrent_score = 100
        elif max_concurrent >= 10:
            concurrent_score = 80
        elif max_concurrent >= 5:
            concurrent_score = 60
        else:
            concurrent_score = 40
            
        summary['key_improvements'].append(
            f"最大并发能力: {max_concurrent} 个请求"
        )
        
        # 计算内存使用得分
        memory_score = 100
        if memory and memory.get('peak_process_memory_gb'):
            peak_memory = memory['peak_process_memory_gb']
            summary['key_improvements'].append(
                f"峰值内存使用: {peak_memory:.2f}GB"
            )
            
            if peak_memory > 2.0:  # 超过2GB
                memory_score -= 30
            elif peak_memory < 1.0:  # 低于1GB
                memory_score += 10
        
        # 计算缓存效果得分
        cache_score = 0
        if cache and cache.get('hit_ratio'):
            hit_ratio = cache['hit_ratio']
            summary['key_improvements'].append(
                f"缓存命中率: {hit_ratio:.1%}"
            )
            
            if hit_ratio > 0.7:  # 70%以上
                cache_score = 100
            elif hit_ratio > 0.5:  # 50%以上
                cache_score = 80
            elif hit_ratio > 0.2:  # 20%以上
                cache_score = 60
        
        # 综合得分
        summary['overall_score'] = round(
            (response_score * 0.4 + concurrent_score * 0.3 + 
             memory_score * 0.2 + cache_score * 0.1), 1
        )
        
        # 性能等级
        if summary['overall_score'] >= 90:
            summary['performance_grade'] = 'A+ 🚀'
        elif summary['overall_score'] >= 80:
            summary['performance_grade'] = 'A 🌟'
        elif summary['overall_score'] >= 70:
            summary['performance_grade'] = 'B 💪'
        elif summary['overall_score'] >= 60:
            summary['performance_grade'] = 'C 📈'
        else:
            summary['performance_grade'] = 'D ⚠️'
        
        # 建议
        if response_score < 80:
            summary['recommendations'].append(
                "考虑进一步优化模型推理速度或增加缓存"
            )
        if concurrent_score < 80:
            summary['recommendations'].append(
                "需要提升并发处理能力，可能需增加worker数量"
            )
        if memory_score < 90:
            summary['recommendations'].append(
                "内存使用较高，建议优化内存管理或增加硬件资源"
            )
        
        if not summary['recommendations']:
            summary['recommendations'].append(
                "🎉 系统性能优异，已达到优化目标!"
            )
        
        return summary
    
    def _save_results(self, results):
        """保存测试结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"performance_benchmark_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n📁 测试结果已保存到: {filename}")
    
    def _generate_performance_report(self, results):
        """生成性能报告"""
        report = f"""
# 🌩️ 智能电网负荷预测系统 - 性能基准测试报告

**测试时间**: {results['timestamp']}
**测试环境**: {results.get('test_config', {}).get('base_url', 'Unknown')}

## 📊 性能概要

**整体评分**: {results['summary']['overall_score']}/100 {results['summary']['performance_grade']}

### 🔑 关键改进

"""
        
        for improvement in results['summary']['key_improvements']:
            report += f"- {improvement}\n"
        
        report += "\n### 💡 优化建议\n\n"
        for recommendation in results['summary']['recommendations']:
            report += f"- {recommendation}\n"
        
        # 详细数据
        report += f"""

## 📈 详细性能数据

### 响应时间分析
- 测试请求数: {results['response_times'].get('total_requests', 'N/A')}
- 平均响应时间: {results['response_times'].get('mean_ms', 'N/A'):.2f}ms
- 第95百分位: {results['response_times'].get('p95_ms', 'N/A'):.2f}ms
- 第99百分位: {results['response_times'].get('p99_ms', 'N/A'):.2f}ms
- 成功率: {results['response_times'].get('success_rate', 0):.1%}

### 并发性能
"""
        
        if results['concurrency']:
            for level, data in results['concurrency'].items():
                report += f"- {level}并发: 成功率{data.get('success_rate', 0):.1%}, "
                report += f"平均响应{data.get('avg_response_time_ms', 0):.2f}ms\n"
        
        report += f"""
### 内存使用
- 峰值内存占用: {results['memory_usage'].get('peak_process_memory_gb', 'N/A'):.2f}GB
- 平均内存占用: {results['memory_usage'].get('avg_process_memory_gb', 'N/A'):.2f}GB
- 内存增长: {results['memory_usage'].get('memory_growth_gb', 'N/A'):.2f}GB

### 缓存性能
- 缓存命中率: {results['cache_performance'].get('hit_ratio', 0):.1%}
- 缓存加速比: {results['cache_performance'].get('speedup_factor', 1):.2f}x

## 🎯 优化验证

✓ **单次预测时间**: {'✅ <30秒' if results['response_times'].get('p95_ms', 30000) < 30000 else '❌ 需优化'}
✓ **并发支持**: {'✅ 10+并发' if max([level for level, data in results['concurrency'].items() if data.get('success_rate', 0) > 0.8], default=0) >= 10 else '❌ 需优化'}
✓ **内存占用**: {'✅ <2GB' if results['memory_usage'].get('peak_process_memory_gb', 2.1) < 2.0 else '❌ 需优化'}

---

*报告生成时间: {datetime.now().isoformat()}*
        """
        
        # 保存报告
        report_filename = f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"📋 性能报告已保存: {report_filename}")

def main():
    """主函数"""
    print("🌩️ 智能电网负荷预测系统 - 性能基准测试工具")
    print("=" * 60)
    
    # 配置测试
    config = BenchmarkConfig(
        base_url="http://localhost:8000",  # 修改为实际的API地址
        num_requests=50,  # 减少默认请求数以加快速度
        concurrency_levels=[5, 10, 15],
        timeout=30.0,
        warmup_requests=5
    )
    
    try:
        # 创建基准测试实例
        benchmark = PerformanceBenchmark(config)
        
        # 运行基准测试
        results = asyncio.run(benchmark.run_comprehensive_benchmark())
        
        # 显示摘要
        print("\n" + "="*60)
        print("🏆 基准测试完成!")
        print(f"📊 整体评分: {results['summary']['overall_score']}/100 {results['summary']['performance_grade']}")
        print("\n🔑 关键指标:")
        
        for improvement in results['summary']['key_improvements']:
            print(f"   • {improvement}")
        
        print("\n💡 建议:")
        for recommendation in results['summary']['recommendations']:
            print(f"   • {recommendation}")
        
        print("\n✅ 详细结果已保存到JSON文件和Markdown报告")
        
    except KeyboardInterrupt:
        print("\n⚠️  测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        raise

if __name__ == "__main__":
    main()