#!/usr/bin/env python3
"""
Cloud Cost Report - Generate cost reports and analysis for cloud jobs.
Provides various reporting views including job summaries, cost trends, and budget analysis.
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from job_manager import get_job_manager
from cost_tracker import CloudCostTracker
import sqlite3

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CostReporter:
    """Generate cost reports and analysis."""
    
    def __init__(self):
        self.job_manager = get_job_manager()
        self.cost_tracker = CloudCostTracker()
    
    def generate_job_summary(self, job_id: str) -> Dict[str, Any]:
        """Generate detailed cost summary for a specific job."""
        summary = self.job_manager.get_cost_summary(job_id)
        if not summary:
            return {'error': f'Job {job_id} not found'}
        
        # Add additional calculations
        if summary.get('actual_cost') and summary.get('estimated_cost'):
            summary['cost_accuracy'] = {
                'estimated': summary['estimated_cost'],
                'actual': summary['actual_cost'],
                'difference': summary['actual_cost'] - summary['estimated_cost'],
                'accuracy_percent': (1 - abs(summary['actual_cost'] - summary['estimated_cost']) / summary['estimated_cost']) * 100
            }
        
        return summary
    
    def generate_cost_trends(self, days: int = 30, provider: Optional[str] = None) -> Dict[str, Any]:
        """Generate cost trends over time."""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            with sqlite3.connect(self.job_manager.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # Build query based on filters
                where_clause = "WHERE created_at >= ?"
                params = [start_date.isoformat()]
                
                if provider:
                    where_clause += " AND provider = ?"
                    params.append(provider.upper())
                
                # Get jobs with costs
                cursor = conn.execute(f'''
                    SELECT 
                        DATE(created_at) as date,
                        provider,
                        COUNT(*) as job_count,
                        SUM(COALESCE(actual_cost, estimated_cost, 0)) as total_cost,
                        AVG(COALESCE(actual_cost, estimated_cost, 0)) as avg_cost,
                        SUM(CASE WHEN actual_cost IS NOT NULL THEN actual_cost ELSE 0 END) as confirmed_cost,
                        SUM(CASE WHEN actual_cost IS NULL THEN COALESCE(estimated_cost, 0) ELSE 0 END) as estimated_cost
                    FROM jobs 
                    {where_clause}
                    GROUP BY DATE(created_at), provider
                    ORDER BY date DESC, provider
                ''', params)
                
                daily_costs = []
                for row in cursor.fetchall():
                    daily_costs.append(dict(row))
                
                # Calculate totals
                total_jobs = sum(row['job_count'] for row in daily_costs)
                total_cost = sum(row['total_cost'] for row in daily_costs)
                total_confirmed = sum(row['confirmed_cost'] for row in daily_costs)
                total_estimated = sum(row['estimated_cost'] for row in daily_costs)
                
                # Group by provider
                provider_summary = {}
                for row in daily_costs:
                    provider_name = row['provider']
                    if provider_name not in provider_summary:
                        provider_summary[provider_name] = {
                            'job_count': 0,
                            'total_cost': 0,
                            'confirmed_cost': 0,
                            'estimated_cost': 0
                        }
                    
                    provider_summary[provider_name]['job_count'] += row['job_count']
                    provider_summary[provider_name]['total_cost'] += row['total_cost']
                    provider_summary[provider_name]['confirmed_cost'] += row['confirmed_cost']
                    provider_summary[provider_name]['estimated_cost'] += row['estimated_cost']
                
                return {
                    'period': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'days': days
                    },
                    'totals': {
                        'job_count': total_jobs,
                        'total_cost': total_cost,
                        'confirmed_cost': total_confirmed,
                        'estimated_cost': total_estimated,
                        'average_job_cost': total_cost / total_jobs if total_jobs > 0 else 0
                    },
                    'provider_breakdown': provider_summary,
                    'daily_costs': daily_costs
                }
        
        except Exception as e:
            logger.error(f"Failed to generate cost trends: {e}")
            return {'error': str(e)}
    
    def generate_budget_analysis(self) -> Dict[str, Any]:
        """Analyze budget performance across all jobs."""
        try:
            with sqlite3.connect(self.job_manager.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # Get jobs with budget limits
                cursor = conn.execute('''
                    SELECT 
                        job_id,
                        provider,
                        instance_type,
                        status,
                        budget_limit,
                        COALESCE(actual_cost, estimated_cost, 0) as current_cost,
                        actual_cost IS NOT NULL as has_actual_cost,
                        created_at
                    FROM jobs 
                    WHERE budget_limit IS NOT NULL
                    ORDER BY created_at DESC
                ''')
                
                budget_jobs = []
                for row in cursor.fetchall():
                    job = dict(row)
                    
                    if job['budget_limit'] > 0:
                        job['budget_usage_percent'] = (job['current_cost'] / job['budget_limit']) * 100
                        job['over_budget'] = job['current_cost'] > job['budget_limit']
                        job['remaining_budget'] = job['budget_limit'] - job['current_cost']
                    else:
                        job['budget_usage_percent'] = 0
                        job['over_budget'] = False
                        job['remaining_budget'] = 0
                    
                    budget_jobs.append(job)
                
                # Calculate statistics
                total_jobs = len(budget_jobs)
                over_budget_jobs = [job for job in budget_jobs if job['over_budget']]
                within_budget_jobs = [job for job in budget_jobs if not job['over_budget']]
                
                total_budget_allocated = sum(job['budget_limit'] for job in budget_jobs)
                total_spent = sum(job['current_cost'] for job in budget_jobs)
                total_savings = sum(job['remaining_budget'] for job in within_budget_jobs)
                total_overrun = sum(job['current_cost'] - job['budget_limit'] for job in over_budget_jobs)
                
                return {
                    'summary': {
                        'total_jobs_with_budget': total_jobs,
                        'jobs_within_budget': len(within_budget_jobs),
                        'jobs_over_budget': len(over_budget_jobs),
                        'budget_success_rate': (len(within_budget_jobs) / total_jobs * 100) if total_jobs > 0 else 0,
                        'total_budget_allocated': total_budget_allocated,
                        'total_spent': total_spent,
                        'total_savings': total_savings,
                        'total_overrun': total_overrun,
                        'budget_utilization_percent': (total_spent / total_budget_allocated * 100) if total_budget_allocated > 0 else 0
                    },
                    'over_budget_jobs': over_budget_jobs,
                    'recent_budget_jobs': budget_jobs[:10]  # Last 10 jobs with budgets
                }
        
        except Exception as e:
            logger.error(f"Failed to generate budget analysis: {e}")
            return {'error': str(e)}
    
    def generate_provider_comparison(self, days: int = 30) -> Dict[str, Any]:
        """Compare costs across cloud providers."""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            with sqlite3.connect(self.job_manager.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                cursor = conn.execute('''
                    SELECT 
                        provider,
                        COUNT(*) as job_count,
                        AVG(COALESCE(actual_cost, estimated_cost, 0)) as avg_cost,
                        MIN(COALESCE(actual_cost, estimated_cost, 0)) as min_cost,
                        MAX(COALESCE(actual_cost, estimated_cost, 0)) as max_cost,
                        SUM(COALESCE(actual_cost, estimated_cost, 0)) as total_cost,
                        AVG(price_per_hour) as avg_price_per_hour,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_jobs,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_jobs
                    FROM jobs 
                    WHERE created_at >= ?
                    GROUP BY provider
                    ORDER BY total_cost DESC
                ''', (start_date.isoformat(),))
                
                provider_stats = []
                for row in cursor.fetchall():
                    stats = dict(row)
                    
                    # Calculate success rate
                    if stats['job_count'] > 0:
                        stats['success_rate'] = (stats['completed_jobs'] / stats['job_count']) * 100
                    else:
                        stats['success_rate'] = 0
                    
                    provider_stats.append(stats)
                
                # Find best and worst providers
                if provider_stats:
                    cheapest_provider = min(provider_stats, key=lambda x: x['avg_cost'])
                    most_reliable = max(provider_stats, key=lambda x: x['success_rate'])
                    most_used = max(provider_stats, key=lambda x: x['job_count'])
                else:
                    cheapest_provider = most_reliable = most_used = None
                
                return {
                    'period': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'days': days
                    },
                    'provider_stats': provider_stats,
                    'recommendations': {
                        'cheapest_provider': cheapest_provider,
                        'most_reliable_provider': most_reliable,
                        'most_used_provider': most_used
                    }
                }
        
        except Exception as e:
            logger.error(f"Failed to generate provider comparison: {e}")
            return {'error': str(e)}
    
    def print_job_summary(self, job_id: str):
        """Print formatted job cost summary."""
        summary = self.generate_job_summary(job_id)
        
        if 'error' in summary:
            print(f"Error: {summary['error']}")
            return
        
        print(f"\n{'='*60}")
        print(f"COST SUMMARY FOR JOB: {job_id}")
        print(f"{'='*60}")
        
        print(f"Provider: {summary['provider']}")
        print(f"Instance Type: {summary['instance_type']}")
        print(f"Status: {summary['status']}")
        print(f"Region: {summary.get('region', 'N/A')}")
        
        print(f"\n{'Cost Information':<30}")
        print(f"{'-'*40}")
        
        if summary.get('estimated_cost'):
            print(f"{'Estimated Cost:':<25} ${summary['estimated_cost']:.4f}")
        
        if summary.get('actual_cost'):
            print(f"{'Actual Cost:':<25} ${summary['actual_cost']:.4f}")
            if summary.get('cost_retrieved_at'):
                print(f"{'Cost Retrieved:':<25} {summary['cost_retrieved_at']}")
        else:
            print(f"{'Current Runtime Cost:':<25} ${summary['current_runtime_cost']:.4f}")
        
        if summary.get('budget_limit'):
            print(f"{'Budget Limit:':<25} ${summary['budget_limit']:.2f}")
            if summary['within_budget']:
                print(f"{'Budget Status:':<25} ✓ Within budget")
            else:
                print(f"{'Budget Status:':<25} ✗ Over budget by ${summary.get('over_budget_amount', 0):.4f}")
        
        if summary.get('cost_accuracy'):
            acc = summary['cost_accuracy']
            print(f"\n{'Cost Accuracy Analysis':<30}")
            print(f"{'-'*40}")
            print(f"{'Estimated:':<25} ${acc['estimated']:.4f}")
            print(f"{'Actual:':<25} ${acc['actual']:.4f}")
            print(f"{'Difference:':<25} ${acc['difference']:.4f}")
            print(f"{'Accuracy:':<25} {acc['accuracy_percent']:.1f}%")
        
        if summary.get('cost_breakdown'):
            print(f"\n{'Detailed Cost Breakdown':<30}")
            print(f"{'-'*40}")
            for item in summary['cost_breakdown']:
                print(f"  {item['cost_type']:<20} ${item['amount']:.4f} ({item['currency']})")
    
    def print_cost_trends(self, days: int = 30, provider: Optional[str] = None):
        """Print formatted cost trends report."""
        trends = self.generate_cost_trends(days, provider)
        
        if 'error' in trends:
            print(f"Error: {trends['error']}")
            return
        
        print(f"\n{'='*80}")
        print(f"COST TRENDS REPORT ({days} days)")
        if provider:
            print(f"Provider: {provider}")
        print(f"{'='*80}")
        
        totals = trends['totals']
        print(f"Total Jobs: {totals['job_count']}")
        print(f"Total Cost: ${totals['total_cost']:.2f}")
        print(f"  - Confirmed: ${totals['confirmed_cost']:.2f}")
        print(f"  - Estimated: ${totals['estimated_cost']:.2f}")
        print(f"Average Job Cost: ${totals['average_job_cost']:.4f}")
        
        print(f"\n{'Provider Breakdown':<20}")
        print(f"{'-'*50}")
        print(f"{'Provider':<10} | {'Jobs':<6} | {'Total Cost':<12} | {'Avg Cost':<10}")
        print(f"{'-'*50}")
        
        for provider_name, stats in trends['provider_breakdown'].items():
            avg_cost = stats['total_cost'] / stats['job_count'] if stats['job_count'] > 0 else 0
            print(f"{provider_name:<10} | {stats['job_count']:<6} | ${stats['total_cost']:<11.2f} | ${avg_cost:<9.4f}")
        
        if trends['daily_costs']:
            print(f"\n{'Recent Daily Costs':<20}")
            print(f"{'-'*60}")
            print(f"{'Date':<12} | {'Provider':<8} | {'Jobs':<6} | {'Cost':<10}")
            print(f"{'-'*60}")
            
            for day in trends['daily_costs'][:10]:  # Show last 10 days
                print(f"{day['date']:<12} | {day['provider']:<8} | {day['job_count']:<6} | ${day['total_cost']:<9.2f}")
    
    def print_budget_analysis(self):
        """Print formatted budget analysis report."""
        analysis = self.generate_budget_analysis()
        
        if 'error' in analysis:
            print(f"Error: {analysis['error']}")
            return
        
        print(f"\n{'='*70}")
        print(f"BUDGET ANALYSIS REPORT")
        print(f"{'='*70}")
        
        summary = analysis['summary']
        print(f"Total Jobs with Budget: {summary['total_jobs_with_budget']}")
        print(f"Jobs Within Budget: {summary['jobs_within_budget']} ({summary['budget_success_rate']:.1f}%)")
        print(f"Jobs Over Budget: {summary['jobs_over_budget']}")
        
        print(f"\nBudget Performance:")
        print(f"  Total Allocated: ${summary['total_budget_allocated']:.2f}")
        print(f"  Total Spent: ${summary['total_spent']:.2f}")
        print(f"  Total Savings: ${summary['total_savings']:.2f}")
        print(f"  Total Overrun: ${summary['total_overrun']:.2f}")
        print(f"  Utilization: {summary['budget_utilization_percent']:.1f}%")
        
        if analysis['over_budget_jobs']:
            print(f"\n{'Jobs Over Budget':<20}")
            print(f"{'-'*80}")
            print(f"{'Job ID':<10} | {'Provider':<8} | {'Budget':<8} | {'Spent':<8} | {'Over By':<8}")
            print(f"{'-'*80}")
            
            for job in analysis['over_budget_jobs'][:10]:  # Show first 10
                over_amount = job['current_cost'] - job['budget_limit']
                print(f"{job['job_id']:<10} | {job['provider']:<8} | ${job['budget_limit']:<7.2f} | ${job['current_cost']:<7.2f} | ${over_amount:<7.2f}")
    
    def print_provider_comparison(self, days: int = 30):
        """Print formatted provider comparison report."""
        comparison = self.generate_provider_comparison(days)
        
        if 'error' in comparison:
            print(f"Error: {comparison['error']}")
            return
        
        print(f"\n{'='*90}")
        print(f"PROVIDER COMPARISON REPORT ({days} days)")
        print(f"{'='*90}")
        
        if not comparison['provider_stats']:
            print("No data available for the specified period.")
            return
        
        print(f"{'Provider':<8} | {'Jobs':<6} | {'Total Cost':<12} | {'Avg Cost':<10} | {'Success %':<9} | {'Avg $/hr':<8}")
        print(f"{'-'*90}")
        
        for stats in comparison['provider_stats']:
            print(f"{stats['provider']:<8} | {stats['job_count']:<6} | ${stats['total_cost']:<11.2f} | "
                  f"${stats['avg_cost']:<9.4f} | {stats['success_rate']:<8.1f}% | ${stats['avg_price_per_hour']:<7.4f}")
        
        recommendations = comparison['recommendations']
        print(f"\n{'Recommendations':<20}")
        print(f"{'-'*40}")
        
        if recommendations['cheapest_provider']:
            cheapest = recommendations['cheapest_provider']
            print(f"Cheapest: {cheapest['provider']} (avg ${cheapest['avg_cost']:.4f} per job)")
        
        if recommendations['most_reliable_provider']:
            reliable = recommendations['most_reliable_provider']
            print(f"Most Reliable: {reliable['provider']} ({reliable['success_rate']:.1f}% success rate)")
        
        if recommendations['most_used_provider']:
            popular = recommendations['most_used_provider']
            print(f"Most Used: {popular['provider']} ({popular['job_count']} jobs)")


def main():
    """Main function for cost reporting."""
    parser = argparse.ArgumentParser(description="Generate cost reports for cloud jobs")
    
    # Report type selection
    subparsers = parser.add_subparsers(dest='command', help='Report type')
    
    # Job summary
    job_parser = subparsers.add_parser('job', help='Detailed cost summary for a specific job')
    job_parser.add_argument('job_id', help='Job ID to analyze')
    
    # Cost trends
    trends_parser = subparsers.add_parser('trends', help='Cost trends over time')
    trends_parser.add_argument('--days', type=int, default=30, help='Number of days to analyze (default: 30)')
    trends_parser.add_argument('--provider', choices=['AWS', 'GCP', 'Azure'], help='Filter by provider')
    trends_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Budget analysis
    budget_parser = subparsers.add_parser('budget', help='Budget performance analysis')
    budget_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Provider comparison
    compare_parser = subparsers.add_parser('compare', help='Compare costs across providers')
    compare_parser.add_argument('--days', type=int, default=30, help='Number of days to analyze (default: 30)')
    compare_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Retrieve missing costs
    retrieve_parser = subparsers.add_parser('retrieve-costs', help='Retrieve missing actual costs')
    retrieve_parser.add_argument('--job-id', help='Specific job ID to process')
    retrieve_parser.add_argument('--max-jobs', type=int, default=10, help='Maximum jobs to process')
    retrieve_parser.add_argument('--days-back', type=int, default=7, help='How many days back to look')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    reporter = CostReporter()
    
    try:
        if args.command == 'job':
            if hasattr(args, 'json') and args.json:
                summary = reporter.generate_job_summary(args.job_id)
                print(json.dumps(summary, indent=2))
            else:
                reporter.print_job_summary(args.job_id)
        
        elif args.command == 'trends':
            if args.json:
                trends = reporter.generate_cost_trends(args.days, args.provider)
                print(json.dumps(trends, indent=2))
            else:
                reporter.print_cost_trends(args.days, args.provider)
        
        elif args.command == 'budget':
            if args.json:
                analysis = reporter.generate_budget_analysis()
                print(json.dumps(analysis, indent=2))
            else:
                reporter.print_budget_analysis()
        
        elif args.command == 'compare':
            if args.json:
                comparison = reporter.generate_provider_comparison(args.days)
                print(json.dumps(comparison, indent=2))
            else:
                reporter.print_provider_comparison(args.days)
        
        elif args.command == 'retrieve-costs':
            if args.job_id:
                success = reporter.cost_tracker.retrieve_job_cost(args.job_id, force_refresh=True)
                if success:
                    print(f"Successfully retrieved cost for job {args.job_id}")
                else:
                    print(f"Failed to retrieve cost for job {args.job_id}")
                    sys.exit(1)
            else:
                results = reporter.cost_tracker.batch_retrieve_costs(args.max_jobs, args.days_back)
                print(f"Processed {results['processed']} jobs: {results['successful']} successful, {results['failed']} failed")
    
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()