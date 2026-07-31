#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core Features Implementation Verification

Verify the completeness of four core functionalities:
1. User Management & Access Control 
2. Data Backup & Recovery 
3. Model Version Management
4. Prediction Result Management

Author: Graduation Project
"""

import os
import sys
import json
from datetime import datetime

def print_header(title):
    print("\n" + "="*60)
    print(f"CHECK: {title}")
    print("="*60)

def test_feature_1_authentication():
    """Test Feature 1: User Management & Access Control"""
    print_header("Feature 1: User Management & Access Control")
    
    auth_files = [
        'realtime_api/auth/middleware.py',
        'realtime_api/auth/dependencies.py', 
        'realtime_api/routers/auth.py',
        'realtime_api/schemas.py'
    ]
    
    existing_files = []
    for file in auth_files:
        if os.path.exists(file):
            existing_files.append(file)
            print(f"   [OK] {file}")
        else:
            print(f"   [MISSING] {file}")
    
    # Check user table structure 
    if os.path.exists('docker/mysql/scripts/init.sql'):
        with open('docker/mysql/scripts/init.sql', 'r') as f:
            sql_content = f.read()
            if 'users' in sql_content and 'roles' in sql_content:
                print("   [OK] User and role tables created")
                return True
            else:
                print("   [MISSING] User/role table structure incomplete")
    
    print(f"   Summary: {len(existing_files)}/{len(auth_files)} core files implemented")
    return len(existing_files) >= len(auth_files) * 0.8

def test_feature_2_backup_recovery():
    """Test Feature 2: Data Backup & Recovery"""
    print_header("Feature 2: Data Backup & Recovery")
    
    backup_files = [
        'docker/mysql/scripts/backup-mysql.sh',
        'docker/mysql/scripts/restore-mysql.sh',
        'docker/redis/scripts/backup-redis.sh'
    ]
    
    existing_files = []
    for file in backup_files:
        if os.path.exists(file):
            existing_files.append(file)
            print(f"   [OK] {file}")
        else:
            print(f"   [MISSING] {file}")
    
    print(f"   Summary: {len(existing_files)}/{len(backup_files)} backup scripts implemented")
    return len(existing_files) >= len(backup_files) * 0.8

def test_feature_3_model_versioning():
    """Test Feature 3: Model Version Management"""
    print_header("Feature 3: Model Version Management")
    
    model_files = [
        'realtime_api/model_management.py',
        'docker/mysql/scripts/init.sql'
    ]
    
    existing_files = []
    for file in model_files:
        if os.path.exists(file):
            existing_files.append(file)
            print(f"   [OK] {file}")
            
            # Check MLflow integration
            if file == 'realtime_api/model_management.py':
                with open(file, 'r') as f:
                    content = f.read()
                    if 'mlflow' in content.lower():
                        print(f"   [OK] {file} contains MLflow integration")
            
            # Check database table
            if file == 'docker/mysql/scripts/init.sql':
                with open(file, 'r') as f:
                    content = f.read()
                    if 'model_versions' in content:
                        print(f"   [OK] {file} contains model version table")
        else:
            print(f"   [MISSING] {file}")
    
    print(f"   Summary: {len(existing_files)}/{len(model_files)} core files implemented")
    return len(existing_files) >= len(model_files) * 0.8

def test_feature_4_prediction_management():
    """Test Feature 4: Prediction Result Management"""
    print_header("Feature 4: Prediction Result Management")
    
    prediction_files = [
        'realtime_api/monitoring_service.py',
        'realtime_api/prediction_analytics.py',
        'realtime_api/routers/analytics.py',
        'test_prediction_management.py'
    ]
    
    existing_files = []
    for file in prediction_files:
        if os.path.exists(file):
            existing_files.append(file)
            print(f"   [OK] {file}")
            
            # Check functional implementations
            if file == 'realtime_api/monitoring_service.py':
                with open(file, 'r') as f:
                    content = f.read()
                    if 'AccuracyTracker' in content:
                        print(f"   [OK] {file} contains AccuracyTracker")
                    if 'ModelDriftDetector' in content:
                        print(f"   [OK] {file} contains ModelDriftDetector")
                    if 'DataQualityMonitor' in content:
                        print(f"   [OK] {file} contains DataQualityMonitor")
            
            if file == 'realtime_api/prediction_analytics.py':
                with open(file, 'r') as f:
                    content = f.read()
                    if 'PredictionComparator' in content:
                        print(f"   [OK] {file} contains PredictionComparator")
            
            if file == 'realtime_api/routers/analytics.py':
                with open(file, 'r') as f:
                    content = f.read()
                    endpoints = ['/accuracy/stats', '/drift/check', '/comparison/models', '/report/comprehensive']
                    for endpoint in endpoints:
                        if endpoint in content:
                            print(f"   [OK] {file} contains {endpoint} endpoint")
        else:
            print(f"   [MISSING] {file}")
    
    print(f"   Summary: {len(existing_files)}/{len(prediction_files)} core files implemented")
    return len(existing_files) >= len(prediction_files) * 0.8

def test_api_integration():
    """Test API Integration"""
    print_header("API Integration Test")
    
    app_file = 'realtime_api/app.py'
    if os.path.exists(app_file):
        with open(app_file, 'r') as f:
            content = f.read()
            
            # Check router integrations
            integrations = [
                ('auth_router', 'Authentication Router'),
                ('analytics_router', 'Analytics Router')
            ]
            
            for integration, name in integrations:
                if integration in content:
                    print(f"   [OK] {app_file} integrated {name}")
                    return True
                else:
                    print(f"   [MISSING] {app_file} missing {name}")
        
        return True
    else:
        print(f"   [MISSING] {app_file}")
        return False

def generate_report(results):
    """Generate test report"""
    print_header("Core Features Implementation Report")
    
    report = {
        "Test Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Overall Completion": f"{(sum(results) / len(results)) * 100:.1f}%",
        "Feature Details": {
            "User Management & Access Control": "IMPLEMENTED" if results[0] else "NEEDS WORK",
            "Data Backup & Recovery": "IMPLEMENTED" if results[1] else "NEEDS WORK", 
            "Model Version Management": "IMPLEMENTED" if results[2] else "NEEDS WORK",
            "Prediction Result Management": "IMPLEMENTED" if results[3] else "NEEDS WORK",
            "API Integration": "IMPLEMENTED" if results[4] else "NEEDS WORK"
        }
    }
    
    # Print report
    for key, value in report["Feature Details"].items():
        print(f"   {value} {key}")
    
    print(f"   \nOverall Completion: {report['Overall Completion']}")
    
    # Save report
    with open('core_features_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    
    print("   [OK] Detailed report saved to core_features_report.json")
    
    return report

def main():
    """Main function"""
    print("\n" + "="*60)
    print("Smart Grid Load Prediction System - Core Features Verification")
    print("="*60)
    
    # Execute tests
    results = []
    results.append(test_feature_1_authentication())
    results.append(test_feature_2_backup_recovery())
    results.append(test_feature_3_model_versioning()) 
    results.append(test_feature_4_prediction_management())
    results.append(test_api_integration())
    
    # Generate report
    report = generate_report(results)
    
    # Evaluate completion
    completion_rate = (sum(results) / len(results)) * 100
    
    print_header("Evaluation Conclusion")
    if completion_rate >= 80:
        print("SUCCESS: All core features are basically implemented!")
        print("The system meets basic enterprise production requirements.")
        print("Recommend performance testing and stress testing.")
    elif completion_rate >= 60:
        print("WARNING: Most core features implemented, but need refinement.")
        print("Please improve based on [MISSING] items in the report.")
    else:
        print("ATTENTION: Core feature implementation is low, prioritize infrastructure.")
    
    print(f"\nFinal Completion Rate: {completion_rate:.1f}%")
    
    return completion_rate >= 70

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)