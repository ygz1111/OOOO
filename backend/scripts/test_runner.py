#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 测试运行器

提供完整的测试执行和报告生成功能:
  - 灵活的测试子集选择
  - 覆盖率报告生成
  - 性能测试基准
  - 结果汇总和分析
  - HTML报告生成

使用方式:
  python test_runner.py --all --coverage
  python test_runner.py --unit --report-format html
  python test_runner.py --integration --performance
  python test_runner.py --category exception --verbose
"""

import sys
import os
import argparse
import subprocess
import json
import time
from datetime import datetime
from pathlib import Path
import shutil

def ensure_coverage_dir():
    """确保覆盖率报告目录存在"""
    coverage_dir = Path("coverage_html")
    coverage_dir.mkdir(exist_ok=True)
    return coverage_dir

def run_pytest_tests(pytest_args, extra_args=""):
    """运行pytest测试"""
    cmd = f"python -m pytest {pytest_args} {extra_args}"
    print(f"\n运行测试命令: {cmd}")
    
    result = subprocess.run(cmd, shell=True, capture_output=False)
    return result.returncode

def generate_coverage_reports():
    """生成覆盖率报告"""
    print("\n" + "="*60)
    print("生成测试覆盖率报告...")
    print("="*60)
    
    reports = []
    
    # HTML报告
    try:
        cmd = "python -m coverage html -d coverage_html --show-contexts"
        subprocess.run(cmd, shell=True, check=True)
        reports.append("HTML报告: coverage_html/index.html")
        print("✓ HTML覆盖率报告已生成")
    except subprocess.CalledProcessError as e:
        print(f"✗ HTML报告生成失败: {e}")
    
    # XML报告 (用于CI/CD)
    try:
        cmd = "python -m coverage xml -o coverage.xml"
        subprocess.run(cmd, shell=True, check=True)
        reports.append("XML报告: coverage.xml")
        print("✓ XML覆盖率报告已生成")
    except subprocess.CalledProcessError as e:
        print(f"✗ XML报告生成失败: {e}")
    
    # 终端报告
    try:
        cmd = "python -m coverage report --precision=2"
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print("\n终端覆盖率报告:")
        print(result.stdout)
        reports.append("终端报告: 已显示")
    except subprocess.CalledProcessError as e:
        print(f"✗ 终端报告生成失败: {e}")
    
    return reports

def run_performance_benchmarks():
    """运行性能测试基准"""
    print("\n" + "="*60)
    print("运行性能测试基准...")
    print("="*60)
    
    try:
        cmd = "python -m pytest tests/test_performance.py --benchmark-only --benchmark-json=benchmark_results.json"
        result = subprocess.run(cmd, shell=True, capture_output=False)
        
        if result.returncode == 0:
            # 读取并显示基准结果
            try:
                if Path("benchmark_results.json").exists():
                    with open("benchmark_results.json") as f:
                        benchmarks = json.load(f)
                    
                    print("\n性能测试结果摘要:")
                    print("-" * 40)
                    
                    for benchmark in benchmarks.get('benchmarks', []):
                        name = benchmark.get('name', 'Unknown')
                        stats = benchmark.get('stats', {})
                        mean_time = stats.get('mean', 0) * 1000  # 转换为毫秒
                        min_time = stats.get('min', 0) * 1000
                        max_time = stats.get('max', 0) * 1000
                        
                        print(f"  {name}:")
                        print(f"    平均: {mean_time:.2f}ms")
                        print(f"    范围: {min_time:.2f}ms - {max_time:.2f}ms")
            except Exception as e:
                print(f"基准结果处理失败: {e}")
        
        return result.returncode
        
    except subprocess.CalledProcessError as e:
        print(f"性能测试失败: {e}")
        return 1

def collect_test_results():
    """收集测试结果进行汇总"""
    results_summary = {
        'timestamp': datetime.now().isoformat(),
        'system_info': {
            'python_version': sys.version,
            'platform': sys.platform
        },
        'test_counts': {},
        'failed_tests': [],
        'warnings': [],
        'coverage_summary': {}
    }
    
    # 尝试收集覆盖率数据
    try:
        coverage_file = Path('coverage.json')
        if coverage_file.exists():
            with open(coverage_file) as f:
                coverage_data = json.load(f)
            
            results_summary['coverage_summary'] = {
                'overall_coverage': coverage_data.get('totals', {}).get('percent_covered', 0),
                'covered_lines': coverage_data.get('totals', {}).get('covered_lines', 0),
                'missing_lines': coverage_data.get('totals', {}).get('missing_lines', 0),
                'excluded_lines': coverage_data.get('totals', {}).get('excluded_lines', 0)
            }
    except Exception as e:
        results_summary['warnings'].append(f"覆盖率数据收集失败: {e}")
    
    return results_summary

def generate_html_test_summary(results_summary, test_type_counts):
    """生成HTML测试摘要报告"""
    template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>智能电网负荷预测系统 - 测试报告</title>
    <style>
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background-color: #f5f5f5; 
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
            background-color: white; 
            padding: 30px; 
            border-radius: 8px; 
            box-shadow: 0 2px 10px rgba(0,0,0,0.1); 
        }
        .header { 
            text-align: center; 
            border-bottom: 3px solid #007acc; 
            padding-bottom: 20px; 
            margin-bottom: 30px; 
        }
        .section { 
            margin-bottom: 30px; 
            padding: 20px; 
            background-color: #f9f9f9; 
            border-radius: 5px; 
            border-left: 4px solid #007acc; 
        }
        .metrics-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
            gap: 20px; 
            margin-bottom: 30px; 
        }
        .metric-card { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            color: white; 
            padding: 20px; 
            border-radius: 8px; 
            text-align: center; 
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); 
        }
        .metric-value { 
            font-size: 2em; 
            font-weight: bold; 
            margin-bottom: 5px; 
        }
        .metric-label { 
            font-size: 0.9em; 
            opacity: 0.9; 
        }
        .status-success { color: #28a745; }
        .status-warning { color: #ffc107; }
        .status-error { color: #dc3545; }
        .test-type-list {
            list-style: none;
            padding: 0;
        }
        .test-type-item {
            padding: 10px;
            margin: 5px 0;
            background-color: #e9ecef;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .timestamp {
            font-size: 0.9em;
            color: #666;
            text-align: center;
            margin-top: 20px;
        }
        .coverage-bar {
            width: 100%;
            background-color: #e9ecef;
            height: 20px;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }
        .coverage-fill {
            height: 100%;
            background: linear-gradient(90deg, #ff6b6b, #4ecdc4, #45b7d1, #96ceb4, #ffeaa7, #dda0dd);
            transition: width 0.5s ease;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌩️ 智能电网负荷预测系统</h1>
            <h2>测试执行报告</h2>
        </div>
        
        <div class="section">
            <h3>📊 测试执行概览</h3>
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-value">{total_tests}</div>
                    <div class="metric-label">总测试数</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{test_categories}</div>
                    <div class="metric-label">测试类别</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{coverage_percent:.1f}%</div>
                    <div class="metric-label">代码覆盖率</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{timestamp}</div>
                    <div class="metric-label">完成时间</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h3>📋 测试类别详情</h3>
            <ul class="test-type-list">
                {test_type_details}
            </ul>
        </div>
        
        <div class="section">
            <h3>🎯 代码覆盖率分析</h3>
            <p>整体覆盖率: <strong>{coverage_percent:.2f}%</strong></p>
            
            <div class="coverage-bar">
                <div class="coverage-fill" style="width: {coverage_percent}%"></div>
            </div>
            
            <p>覆盖行数: {covered_lines} | 缺失行数: {missing_lines} | 排除行数: {excluded_lines}</p>
            
            <div class="status-{coverage_status}">
                覆盖率状态: 
                {coverage_status_text}
            </div>
        </div>
        
        <div class="section">
            <h3>🔧 执行环境</h3>
            <p><strong>Python版本:</strong> {python_version}</p>
            <p><strong>操作系统:</strong> {platform}</p>
            <p><strong>执行命令:</strong> {execution_command}</p>
        </div>
        
        <div class="timestamp">
            报告生成时间: {timestamp} | 智能电网负荷预测系统 v1.0
        </div>
    </div>
</body>
</html>
    """
    
    total_tests = sum(test_type_counts.values()) if test_type_counts else 0
    test_categories = len(test_type_counts) if test_type_counts else 0
    
    # 生成测试类别详情列表
    test_type_details = ""
    if test_type_counts:
        for test_type, count in test_type_counts.items():
            test_type_details += f'''
                <li class="test-type-item">
                    <span>✅ {test_type} 测试</span>
                    <span><strong>{count}</strong> 个测试</span>
                </li>
            '''
    
    # 覆盖率状态评估
    coverage_percent = results_summary.get('coverage_summary', {}).get('overall_coverage', 0)
    
    if coverage_percent >= 90:
        coverage_status = "success"
        coverage_status_text = "优秀 🌟🌟🌟"
    elif coverage_percent >= 75:
        coverage_status = "warning"
        coverage_status_text = "良好 🌟🌟"
    else:
        coverage_status = "error"
        coverage_status_text = "需要改进 ⭐"
    
    # 填写模板
    html_content = template.format(
        total_tests=total_tests,
        test_categories=test_categories,
        coverage_percent=coverage_percent,
        timestamp=datetime.now().strftime("%Y年%m月%d日 %H:%M"),
        test_type_details=test_type_details,
        covered_lines=results_summary.get('coverage_summary', {}).get('covered_lines', 0),
        missing_lines=results_summary.get('coverage_summary', {}).get('missing_lines', 0),
        excluded_lines=results_summary.get('coverage_summary', {}).get('excluded_lines', 0),
        coverage_status=coverage_status,
        coverage_status_text=coverage_status_text,
        python_version=sys.version.split()[0],
        platform=sys.platform,
        execution_command=" ".join(sys.argv)
    )
    
    # 保存HTML报告
    report_file = "test_execution_report.html"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return report_file

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='智能电网负荷预测系统测试运行器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例使用:
  python test_runner.py --all                  # 运行所有测试
  python test_runner.py --unit --coverage     # 单元测试+覆盖率
  python test_runner.py --e2e --html         # 端到端测试+HTML报告
  python test_runner.py --exception --bench   # 异常测试+基准
        """
    )
    
    # 测试类型组
    parser.add_argument('--unit', action='store_true', help='运行单元测试')
    parser.add_argument('--integration', action='store_true', help='运行集成测试')
    parser.add_argument('--e2e', action='store_true', help='运行端到端测试')  
    parser.add_argument('--performance', action='store_true', help='运行性能测试')
    parser.add_argument('--exception', action='store_true', help='运行异常处理测试')
    parser.add_argument('--all', action='store_true', help='运行所有测试')
    
    # 输出配置组
    parser.add_argument('--coverage', action='store_true', help='生成覆盖率报告')
    parser.add_argument('--html', action='store_true', help='生成HTML摘要报告')
    parser.add_argument('--benchmark', action='store_true', help='运行性能基准')
    
    # 通用选项
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    parser.add_argument('--no-cleanup', action='store_true', help='不清理临时文件')
    parser.add_argument('--output-dir', default='test_reports', help='报告输出目录')
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    print("\n" + "="*80)
    print("🌩️  智能电网负荷预测系统 - 测试执行框架")
    print("="*80)
    
    # 如果选择--all，运行所有测试类型
    if args.all:
        args.unit = True
        args.integration = True
        args.e2e = True
        args.performance = True
        args.exception = True
    
    # 检查是否至少选择了一种测试类型
    test_types_selected = any([args.unit, args.integration, args.e2e, args.performance, args.exception])
    if not test_types_selected:
        print("请至少指定一种测试类型 (--unit, --integration, --e2e, --performance, --exception, 或 --all)")
        parser.print_help()
        sys.exit(1)
    
    # 确定覆盖率运行模式
    if args.coverage or args.html:
        # 启用覆盖率测量
        coverage_args = "--cov=realtime_api --cov-report=term-missing --cov-report=html:coverage_html --cov-report=json:coverage.json --cov-report=xml:coverage.xml"
    else:
        coverage_args = ""
    
    # 确定详细输出模式
    if args.verbose:
        verbose_args = "-v --tb=line"
    else:
        verbose_args = "--tb=short"
    
    # 运行各个测试类别
    test_type_counts = {}
    exit_codes = []
    
    test_configs = [
        ('unit', '单元', args.unit, 'tests/test_unit_complete.py'),
        ('integration', '集成', args.integration, 'tests/test_integration.py'),
        ('e2e', '端到端', args.e2e, 'tests/test_e2e.py'),
        ('performance', '性能', args.performance, 'tests/test_performance.py'),
        ('exception', '异常处理', args.exception, 'tests/test_exception_handling.py'),
    ]
    
    for test_type, display_name, should_run, test_file in test_configs:
        if should_run:
            if Path(test_file).exists():
                print(f"\n🔄 执行{display_name}测试...")
                
                cmd_args = f"{test_file} {coverage_args} {verbose_args} -m {test_type}"
                exit_code = run_pytest_tests(cmd_args)
                
                test_type_counts[display_name] = f"已执行 ({'成功' if exit_code == 0 else '失败'})"
                exit_codes.append(exit_code)
                
                print(f"{display_name}测试{'完成 ✓' if exit_code == 0 else '失败 ✗'}")
            else:
                print(f"⚠️  {test_file} 文件不存在，跳过{display_name}测试")
                test_type_counts[display_name] = "文件不存在"
    
    # 运行性能基准
    if args.benchmark:
        print("\n🏃 运行性能基准...")
        benchmark_exit_code = run_performance_benchmarks()
        exit_codes.append(benchmark_exit_code)
        test_type_counts['性能基准'] = f"已完成 ({'成功' if benchmark_exit_code == 0 else '失败'})"
    
    # 生成覆盖率报告
    if args.coverage:
        coverage_reports = generate_coverage_reports()
        test_type_counts['覆盖率报告'] = f"{len(coverage_reports)} 种格式已生成"
    
    # 收集测试结果
    results_summary = collect_test_results()
    
    # 生成HTML摘要报告
    if args.html:
        print("\n📊 生成HTML测试摘要报告...")
        html_report = generate_html_test_summary(results_summary, test_type_counts)
        print(f"✓ HTML摘要报告已生成: {html_report}")
        test_type_counts['HTML摘要'] = html_report
    
    # 最终结果汇总
    print("\n" + "="*80)
    print("📋 测试执行完成")
    print("="*80)
    
    if test_type_counts:
        print("\n测试执行汇总:")
        for test_type, status in test_type_counts.items():
            print(f"  • {test_type}: {status}")
    
    # 覆盖率总结
    if args.coverage and 'coverage_summary' in results_summary:
        coverage_data = results_summary['coverage_summary']
        coverage_percent = coverage_data.get('overall_coverage', 0)
        print(f"\n🎯 覆盖率总结: {coverage_percent:.2f}% ({coverage_data.get('covered_lines', 0)}/{coverage_data.get('covered_lines', 0) + coverage_data.get('missing_lines', 0)} 行)")
    
    # 最终退出码
    final_exit_code = 0 if all(code == 0 for code in exit_codes) else 1
    
    if final_exit_code == 0:
        print("\n✅ 所有测试执行成功!")
    else:
        print("\n❌ 部分测试失败，请检查输出日志")
    
    return final_exit_code

if __name__ == "__main__":
    sys.exit(main())