#!/usr/bin/env python3
"""
List and manage cloud jobs.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any
from job_manager import get_job_manager

def format_duration(start_time: str, end_time: str = None) -> str:
    """Format duration between two timestamps."""
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time) if end_time else datetime.now()
        
        duration = end - start
        
        if duration.days > 0:
            return f"{duration.days}d {duration.seconds//3600}h"
        elif duration.seconds >= 3600:
            return f"{duration.seconds//3600}h {(duration.seconds%3600)//60}m"
        elif duration.seconds >= 60:
            return f"{duration.seconds//60}m"
        else:
            return f"{duration.seconds}s"
    except:
        return "unknown"


def format_cost(cost: float) -> str:
    """Format cost with appropriate precision."""
    if cost == 0:
        return "$0.00"
    elif cost < 0.01:
        return f"${cost:.4f}"
    else:
        return f"${cost:.2f}"


def display_jobs_table(jobs: List[Dict[str, Any]], detailed: bool = False):
    """Display jobs in a formatted table."""
    if not jobs:
        print("No jobs found.")
        return
    
    # Calculate current costs for running jobs
    jm = get_job_manager()
    for job in jobs:
        job['current_cost'] = jm.calculate_job_cost(job['job_id'])
    
    # Basic table
    if not detailed:
        print("=" * 120)
        print(f"{'Job ID':<12} | {'Status':<11} | {'Provider':<8} | {'Instance':<15} | {'Region':<15} | {'Duration':<10} | {'Cost':<8}")
        print("=" * 120)
        
        for job in jobs:
            duration = format_duration(job['created_at'], job.get('completed_at'))
            cost = format_cost(job['current_cost'])
            
            print(f"{job['job_id']:<12} | {job['status']:<11} | {job['provider']:<8} | "
                  f"{job['instance_type']:<15} | {job['region']:<15} | {duration:<10} | {cost:<8}")
    
    # Detailed table
    else:
        for i, job in enumerate(jobs):
            if i > 0:
                print()
            
            print("=" * 80)
            print(f"Job: {job['job_id']} ({job['status'].upper()})")
            print("=" * 80)
            
            print(f"Provider: {job['provider']}")
            print(f"Instance: {job['instance_type']} in {job['region']}")
            
            if job.get('instance_id'):
                print(f"Instance ID: {job['instance_id']}")
            
            if job.get('public_ip'):
                print(f"Public IP: {job['public_ip']}")
            
            print(f"Created: {job['created_at']}")
            
            if job.get('started_at'):
                print(f"Started: {job['started_at']}")
            
            if job.get('completed_at'):
                print(f"Completed: {job['completed_at']}")
            
            duration = format_duration(job['created_at'], job.get('completed_at'))
            print(f"Duration: {duration}")
            
            cost = format_cost(job['current_cost'])
            print(f"Cost: {cost}")
            
            if job.get('s3_input_path'):
                print(f"Input: {job['s3_input_path']}")
            
            if job.get('gdrive_path'):
                print(f"Results: gdrive:{job['gdrive_path']}")
            
            if job.get('basis_set'):
                print(f"Basis: {job['basis_set']}")


def display_jobs_summary(jobs: List[Dict[str, Any]]):
    """Display summary statistics."""
    if not jobs:
        return
    
    # Calculate totals
    jm = get_job_manager()
    
    total_jobs = len(jobs)
    running_jobs = len([j for j in jobs if j['status'] in ['launched', 'running']])
    completed_jobs = len([j for j in jobs if j['status'] == 'completed'])
    failed_jobs = len([j for j in jobs if j['status'] == 'failed'])
    
    total_cost = sum(jm.calculate_job_cost(j['job_id']) for j in jobs)
    
    # Provider breakdown
    providers = {}
    for job in jobs:
        provider = job['provider']
        providers[provider] = providers.get(provider, 0) + 1
    
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Total jobs: {total_jobs}")
    print(f"Running: {running_jobs}")
    print(f"Completed: {completed_jobs}")
    print(f"Failed: {failed_jobs}")
    print(f"Total cost: {format_cost(total_cost)}")
    
    print("\nProviders:")
    for provider, count in sorted(providers.items()):
        print(f"  {provider}: {count}")


def cleanup_old_jobs(days: int, dry_run: bool = False) -> int:
    """Clean up old completed jobs."""
    jm = get_job_manager()
    
    if dry_run:
        # Show what would be deleted
        cutoff_date = datetime.now() - timedelta(days=days)
        old_jobs = []
        
        all_jobs = jm.list_jobs(limit=1000)  # Get more jobs for cleanup
        for job in all_jobs:
            if job['status'] in ['completed', 'failed', 'terminated']:
                job_date = datetime.fromisoformat(job['created_at'])
                if job_date < cutoff_date:
                    old_jobs.append(job)
        
        print(f"Would delete {len(old_jobs)} jobs older than {days} days:")
        for job in old_jobs[:10]:  # Show first 10
            print(f"  {job['job_id']} ({job['status']}) - {job['created_at']}")
        
        if len(old_jobs) > 10:
            print(f"  ... and {len(old_jobs) - 10} more")
        
        return len(old_jobs)
    else:
        return jm.cleanup_completed_jobs(days)


def main():
    """Main function for cloud_list.py"""
    parser = argparse.ArgumentParser(description="List and manage cloud jobs")
    parser.add_argument("--status", choices=['launched', 'running', 'completed', 'failed', 'terminated'],
                       help="Filter by job status")
    parser.add_argument("--provider", choices=['AWS', 'GCP', 'Azure'],
                       help="Filter by cloud provider")
    parser.add_argument("--limit", type=int, default=20,
                       help="Maximum number of jobs to show (default: 20)")
    parser.add_argument("--detailed", "-d", action="store_true",
                       help="Show detailed information")
    parser.add_argument("--summary", action="store_true",
                       help="Show summary statistics")
    parser.add_argument("--json", action="store_true",
                       help="Output raw JSON")
    parser.add_argument("--cleanup", type=int, metavar="DAYS",
                       help="Clean up completed jobs older than N days")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be cleaned up (use with --cleanup)")
    
    args = parser.parse_args()
    
    jm = get_job_manager()
    
    # Handle cleanup
    if args.cleanup is not None:
        deleted_count = cleanup_old_jobs(args.cleanup, args.dry_run)
        
        if args.dry_run:
            print(f"\nUse --cleanup {args.cleanup} without --dry-run to actually delete these jobs")
        else:
            print(f"Cleaned up {deleted_count} old jobs")
        
        sys.exit(0)
    
    # Get jobs
    jobs = jm.list_jobs(status=args.status, limit=args.limit)
    
    # Filter by provider if specified
    if args.provider:
        jobs = [job for job in jobs if job['provider'] == args.provider]
    
    # Output format
    if args.json:
        print(json.dumps(jobs, indent=2))
    else:
        display_jobs_table(jobs, args.detailed)
        
        if args.summary:
            display_jobs_summary(jobs)


if __name__ == "__main__":
    main()