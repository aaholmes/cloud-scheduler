#!/usr/bin/env python3
"""
Test runner script for cloud-scheduler test suite.
Provides different test execution modes and reporting options.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description=""):
    """Run a command and handle errors."""
    if description:
        print(f"\n=== {description} ===")
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode != 0:
        print(f"❌ Failed: {description}")
        return False
    else:
        print(f"✅ Passed: {description}")
        return True


def install_test_dependencies():
    """Install test dependencies."""
    return run_command([
        sys.executable, '-m', 'pip', 'install', '-r', 'requirements-test.txt'
    ], "Installing test dependencies")


def run_unit_tests():
    """Run unit tests only."""
    return run_command([
        sys.executable, '-m', 'pytest', 'tests/unit/', '-v'
    ], "Running unit tests")


def run_integration_tests():
    """Run integration tests only."""
    return run_command([
        sys.executable, '-m', 'pytest', 'tests/integration/', '-v'
    ], "Running integration tests")


def run_all_tests():
    """Run all tests with coverage."""
    return run_command([
        sys.executable, '-m', 'pytest', 'tests/', '-v', '--cov', '--cov-report=term-missing'
    ], "Running all tests with coverage")


def run_dry_run_tests():
    """Run only dry run related tests."""
    return run_command([
        sys.executable, '-m', 'pytest', 'tests/', '-k', 'dry_run', '-v'
    ], "Running dry run tests")


def run_specific_test(test_path):
    """Run a specific test file or test method."""
    return run_command([
        sys.executable, '-m', 'pytest', test_path, '-v'
    ], f"Running specific test: {test_path}")


def run_fast_tests():
    """Run fast tests (unit tests only, no coverage)."""
    return run_command([
        sys.executable, '-m', 'pytest', 'tests/unit/', '-v', '--tb=short'
    ], "Running fast tests (unit tests only)")


def lint_code():
    """Run code linting (if available)."""
    try:
        return run_command([
            sys.executable, '-m', 'flake8', '.', '--exclude=venv,env,tests', '--max-line-length=100'
        ], "Linting code with flake8")
    except FileNotFoundError:
        print("⚠️  flake8 not installed - skipping linting")
        return True


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="Cloud Scheduler Test Runner")
    parser.add_argument('--mode', choices=['unit', 'integration', 'all', 'dry-run', 'fast', 'lint'], 
                       default='all', help="Test mode to run")
    parser.add_argument('--install-deps', action='store_true', 
                       help="Install test dependencies first")
    parser.add_argument('--test', help="Run specific test file or method")
    parser.add_argument('--no-cov', action='store_true', 
                       help="Skip coverage reporting")
    
    args = parser.parse_args()
    
    # Change to project root directory
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    success = True
    
    # Install dependencies if requested
    if args.install_deps:
        if not install_test_dependencies():
            sys.exit(1)
    
    # Run specific test if provided
    if args.test:
        success = run_specific_test(args.test)
    
    # Run tests based on mode
    elif args.mode == 'unit':
        success = run_unit_tests()
    elif args.mode == 'integration':
        success = run_integration_tests()
    elif args.mode == 'dry-run':
        success = run_dry_run_tests()
    elif args.mode == 'fast':
        success = run_fast_tests()
    elif args.mode == 'lint':
        success = lint_code()
    elif args.mode == 'all':
        # Run all tests
        success = True
        
        if not args.no_cov:
            success &= run_all_tests()
        else:
            success &= run_unit_tests()
            success &= run_integration_tests()
        
        # Also run linting
        success &= lint_code()
    
    if success:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()