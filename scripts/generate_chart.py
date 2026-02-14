#!/usr/bin/env python3.11
"""
Generate charts and visualizations for Jarvis (Chief of Staff).
Supports: gantt, risk_heatmap, status_dashboard, workload, phase_progress, bar, pie
Usage: python generate_chart.py <chart_type> <output_path> [options]
"""

import argparse
import json
import sys
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.dates import DateFormatter
import numpy as np
from datetime import datetime, timedelta


# Professional color palette
COLORS = {
    'primary': '#2563EB',
    'secondary': '#64748B',
    'success': '#16A34A',
    'warning': '#D97706',
    'danger': '#DC2626',
    'info': '#0891B2',
    'light': '#F1F5F9',
    'dark': '#1E293B',
    'complete': '#16A34A',
    'in_progress': '#2563EB',
    'not_started': '#94A3B8',
    'at_risk': '#D97706',
    'blocked': '#DC2626',
    'overdue': '#DC2626',
}

STATUS_COLORS = {
    'Complete': COLORS['complete'],
    'In Progress': COLORS['in_progress'],
    'Not Started': COLORS['not_started'],
    'At Risk': COLORS['at_risk'],
    'Blocked': COLORS['blocked'],
    'Overdue': COLORS['overdue'],
}

SEVERITY_COLORS = {
    'CRITICAL': '#DC2626',
    'HIGH': '#EA580C',
    'MEDIUM': '#D97706',
    'LOW': '#16A34A',
}


def setup_style():
    """Apply consistent professional styling."""
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],
        'font.size': 10,
        'axes.titlesize': 14,
        'axes.titleweight': 'bold',
        'axes.labelsize': 11,
        'figure.facecolor': 'white',
        'axes.facecolor': '#FAFBFC',
        'axes.grid': True,
        'grid.alpha': 0.3,
        'grid.color': '#CBD5E1',
    })


def gantt_chart(data, output_path, title="Project Timeline"):
    """Generate a Gantt chart from phase/task data.

    data format: {"phases": [{"name": str, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "status": str, "tasks": [...]}]}
    """
    setup_style()
    phases = data.get('phases', [])
    if not phases:
        print("Error: No phases provided", file=sys.stderr)
        return

    # Flatten tasks
    items = []
    for phase in phases:
        items.append({'name': phase['name'], 'start': phase.get('start'), 'end': phase.get('end'),
                      'status': phase.get('status', 'Not Started'), 'is_phase': True})
        for task in phase.get('tasks', []):
            items.append({'name': f"  {task['name']}", 'start': task.get('start'), 'end': task.get('end'),
                          'status': task.get('status', 'Not Started'), 'is_phase': False})

    fig, ax = plt.subplots(figsize=(14, max(6, len(items) * 0.4)))

    today = datetime.now()
    y_positions = list(range(len(items) - 1, -1, -1))

    for i, item in enumerate(items):
        y = y_positions[i]
        color = STATUS_COLORS.get(item['status'], COLORS['not_started'])

        if item['start'] and item['end']:
            start = datetime.strptime(item['start'], '%Y-%m-%d')
            end = datetime.strptime(item['end'], '%Y-%m-%d')
            duration = (end - start).days
            bar_height = 0.6 if item['is_phase'] else 0.4
            alpha = 1.0 if item['is_phase'] else 0.8
            ax.barh(y, duration, left=start, height=bar_height, color=color, alpha=alpha,
                    edgecolor='white', linewidth=0.5)

        fontweight = 'bold' if item['is_phase'] else 'normal'
        fontsize = 10 if item['is_phase'] else 9
        ax.text(-0.5, y, item['name'], ha='right', va='center', fontsize=fontsize,
                fontweight=fontweight, transform=ax.get_yaxis_transform())

    # Today line
    ax.axvline(x=today, color=COLORS['danger'], linestyle='--', linewidth=1.5, alpha=0.7, label='Today')

    ax.set_yticks(y_positions)
    ax.set_yticklabels([''] * len(items))
    ax.xaxis.set_major_formatter(DateFormatter('%b %Y'))
    ax.set_title(title, pad=20)

    # Legend
    legend_patches = [mpatches.Patch(color=c, label=s) for s, c in STATUS_COLORS.items() if s in {item['status'] for item in items}]
    legend_patches.append(mpatches.Patch(color=COLORS['danger'], label='Today', alpha=0.7))
    ax.legend(handles=legend_patches, loc='upper right', fontsize=8)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Gantt chart saved to {output_path}")


def risk_heatmap(data, output_path, title="Risk Heat Map"):
    """Generate a risk severity heatmap.

    data format: {"risks": [{"id": str, "name": str, "severity": str, "status": str}]}
    """
    setup_style()
    risks = data.get('risks', [])
    if not risks:
        print("Error: No risks provided", file=sys.stderr)
        return

    severity_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    severity_vals = {s: i for i, s in enumerate(severity_order)}

    fig, ax = plt.subplots(figsize=(12, max(4, len(risks) * 0.5)))

    sorted_risks = sorted(risks, key=lambda r: severity_vals.get(r.get('severity', 'LOW'), 3))

    y_pos = range(len(sorted_risks))
    colors = [SEVERITY_COLORS.get(r.get('severity', 'LOW'), COLORS['secondary']) for r in sorted_risks]

    bars = ax.barh(y_pos, [1] * len(sorted_risks), color=colors, height=0.7, edgecolor='white', linewidth=2)

    for i, risk in enumerate(sorted_risks):
        label = f"{risk.get('id', '')}  {risk.get('name', '')}"
        ax.text(0.02, i, label, ha='left', va='center', fontsize=9, fontweight='bold', color='white')
        ax.text(0.98, i, risk.get('severity', ''), ha='right', va='center', fontsize=8, color='white', alpha=0.9)

    ax.set_xlim(0, 1)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_title(title, pad=15)

    legend_patches = [mpatches.Patch(color=c, label=s) for s, c in SEVERITY_COLORS.items()]
    ax.legend(handles=legend_patches, loc='lower right', fontsize=8)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Risk heatmap saved to {output_path}")


def workload_chart(data, output_path, title="Workload Distribution"):
    """Generate a workload distribution bar chart.

    data format: {"people": [{"name": str, "items": int, "blocked": int, "in_progress": int}]}
    """
    setup_style()
    people = data.get('people', [])
    if not people:
        print("Error: No people provided", file=sys.stderr)
        return

    fig, ax = plt.subplots(figsize=(10, max(4, len(people) * 0.6)))

    names = [p['name'] for p in people]
    blocked = [p.get('blocked', 0) for p in people]
    in_progress = [p.get('in_progress', 0) for p in people]
    todo = [p.get('items', 0) - p.get('blocked', 0) - p.get('in_progress', 0) for p in people]

    y_pos = range(len(names))

    ax.barh(y_pos, blocked, color=COLORS['danger'], label='Blocked', height=0.6)
    ax.barh(y_pos, in_progress, left=blocked, color=COLORS['in_progress'], label='In Progress', height=0.6)
    ax.barh(y_pos, todo, left=[b + i for b, i in zip(blocked, in_progress)], color=COLORS['not_started'], label='To Do', height=0.6)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names)
    ax.set_xlabel('Number of Items')
    ax.set_title(title, pad=15)
    ax.legend(loc='lower right', fontsize=9)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Workload chart saved to {output_path}")


def phase_progress(data, output_path, title="Phase Progress"):
    """Generate a phase progress tracker.

    data format: {"phases": [{"name": str, "total": int, "complete": int, "in_progress": int, "status": str}]}
    """
    setup_style()
    phases = data.get('phases', [])
    if not phases:
        print("Error: No phases provided", file=sys.stderr)
        return

    fig, ax = plt.subplots(figsize=(12, max(3, len(phases) * 0.8)))

    y_pos = range(len(phases) - 1, -1, -1)

    for i, phase in enumerate(phases):
        y = list(y_pos)[i]
        total = phase.get('total', 1)
        complete = phase.get('complete', 0)
        in_prog = phase.get('in_progress', 0)
        pct_complete = complete / total if total > 0 else 0
        pct_in_prog = in_prog / total if total > 0 else 0

        # Background bar
        ax.barh(y, 1, color=COLORS['light'], height=0.6, edgecolor='#E2E8F0')
        # Complete portion
        ax.barh(y, pct_complete, color=COLORS['complete'], height=0.6)
        # In progress portion
        ax.barh(y, pct_in_prog, left=pct_complete, color=COLORS['in_progress'], height=0.6, alpha=0.7)

        # Label
        pct_text = f"{int(pct_complete * 100)}%"
        ax.text(1.02, y, pct_text, ha='left', va='center', fontsize=10, fontweight='bold')
        ax.text(-0.02, y, phase['name'], ha='right', va='center', fontsize=10)

    ax.set_xlim(-0.01, 1.15)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_title(title, pad=15)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)

    legend_patches = [
        mpatches.Patch(color=COLORS['complete'], label='Complete'),
        mpatches.Patch(color=COLORS['in_progress'], label='In Progress', alpha=0.7),
        mpatches.Patch(color=COLORS['light'], label='Remaining'),
    ]
    ax.legend(handles=legend_patches, loc='lower right', fontsize=8)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Phase progress chart saved to {output_path}")


def status_dashboard(data, output_path, title="Project Status Dashboard"):
    """Generate a multi-panel status dashboard.

    data format: {"metrics": [{"label": str, "value": str, "status": str}],
                  "phases": [...], "risks_summary": {"critical": int, "high": int, ...}}
    """
    setup_style()

    fig = plt.figure(figsize=(14, 8))
    fig.suptitle(title, fontsize=16, fontweight='bold', y=0.98)

    # KPI cards across the top
    metrics = data.get('metrics', [])
    n_metrics = len(metrics)
    if n_metrics > 0:
        for i, m in enumerate(metrics):
            ax = fig.add_axes([i / n_metrics + 0.02, 0.78, 1 / n_metrics - 0.04, 0.15])
            status_color = STATUS_COLORS.get(m.get('status', ''), COLORS['secondary'])
            ax.set_facecolor(status_color)
            ax.text(0.5, 0.65, m.get('value', ''), ha='center', va='center',
                    fontsize=20, fontweight='bold', color='white', transform=ax.transAxes)
            ax.text(0.5, 0.25, m.get('label', ''), ha='center', va='center',
                    fontsize=9, color='white', alpha=0.9, transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)

    # Risk summary (bottom left)
    risks = data.get('risks_summary', {})
    if risks:
        ax2 = fig.add_axes([0.05, 0.08, 0.4, 0.6])
        categories = list(risks.keys())
        values = list(risks.values())
        colors = [SEVERITY_COLORS.get(c.upper(), COLORS['secondary']) for c in categories]
        bars = ax2.bar(categories, values, color=colors, width=0.6, edgecolor='white')
        for bar, val in zip(bars, values):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                     str(val), ha='center', va='bottom', fontweight='bold', fontsize=11)
        ax2.set_title('RAID Summary', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Count')

    # Phase progress (bottom right)
    phases = data.get('phases', [])
    if phases:
        ax3 = fig.add_axes([0.55, 0.08, 0.4, 0.6])
        names = [p['name'] for p in phases]
        pcts = [p.get('complete', 0) / max(p.get('total', 1), 1) * 100 for p in phases]
        colors = [COLORS['complete'] if p >= 100 else COLORS['in_progress'] if p > 0 else COLORS['not_started'] for p in pcts]
        y_pos = range(len(names) - 1, -1, -1)
        ax3.barh(list(y_pos), pcts, color=colors, height=0.5)
        ax3.set_yticks(list(y_pos))
        ax3.set_yticklabels(names, fontsize=9)
        ax3.set_xlim(0, 110)
        ax3.set_xlabel('% Complete')
        ax3.set_title('Phase Progress', fontsize=12, fontweight='bold')
        for y, pct in zip(y_pos, pcts):
            ax3.text(pct + 1, y, f"{int(pct)}%", va='center', fontsize=9)

    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Status dashboard saved to {output_path}")


def bar_chart(data, output_path, title="Bar Chart"):
    """Simple bar chart. data: {"labels": [...], "values": [...], "xlabel": str, "ylabel": str}"""
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = data.get('labels', [])
    values = data.get('values', [])
    colors = data.get('colors', [COLORS['primary']] * len(labels))
    ax.bar(labels, values, color=colors, width=0.6)
    ax.set_xlabel(data.get('xlabel', ''))
    ax.set_ylabel(data.get('ylabel', ''))
    ax.set_title(title, pad=15)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Bar chart saved to {output_path}")


def pie_chart(data, output_path, title="Pie Chart"):
    """Simple pie chart. data: {"labels": [...], "values": [...]}"""
    setup_style()
    fig, ax = plt.subplots(figsize=(8, 8))
    labels = data.get('labels', [])
    values = data.get('values', [])
    colors = data.get('colors', [COLORS['primary'], COLORS['info'], COLORS['warning'],
                                  COLORS['success'], COLORS['danger'], COLORS['secondary']])
    ax.pie(values, labels=labels, colors=colors[:len(labels)], autopct='%1.1f%%',
           startangle=90, pctdistance=0.85)
    ax.set_title(title, pad=20)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Pie chart saved to {output_path}")


CHART_TYPES = {
    'gantt': gantt_chart,
    'risk_heatmap': risk_heatmap,
    'workload': workload_chart,
    'phase_progress': phase_progress,
    'status_dashboard': status_dashboard,
    'bar': bar_chart,
    'pie': pie_chart,
}


def main():
    parser = argparse.ArgumentParser(description='Generate charts for Jarvis')
    parser.add_argument('chart_type', choices=CHART_TYPES.keys(), help='Type of chart to generate')
    parser.add_argument('output_path', help='Output file path (PNG/SVG)')
    parser.add_argument('--data', help='JSON string with chart data')
    parser.add_argument('--data-file', help='Path to JSON file with chart data')
    parser.add_argument('--title', default=None, help='Chart title')

    args = parser.parse_args()

    if args.data_file:
        with open(args.data_file) as f:
            data = json.load(f)
    elif args.data:
        data = json.loads(args.data)
    else:
        data = json.load(sys.stdin)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(args.output_path)), exist_ok=True)

    title = args.title or data.get('title', args.chart_type.replace('_', ' ').title())
    CHART_TYPES[args.chart_type](data, args.output_path, title=title)


if __name__ == '__main__':
    main()
