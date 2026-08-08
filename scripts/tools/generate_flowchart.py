"""生成任务编排流程 PNG 图"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(14, 11))
ax.set_xlim(0, 14)
ax.set_ylim(0, 11)
ax.axis('off')

def draw_box(x, y, w, h, text, color='lightblue', fontsize=9):
    rect = mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                                   facecolor=color, edgecolor='black', linewidth=1.5)
    ax.add_patch(rect)
    ax.text(x + w/2, y + h/2, text, ha='center', va='center',
            fontsize=fontsize, weight='bold', linespacing=1.4)

def draw_arrow(x1, y1, x2, y2, style='->'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color='black', lw=1.5))

# 标题
ax.text(7, 10.5, 'DeepAgent 复杂任务编排流程', ha='center', fontsize=15, weight='bold')
ax.text(7, 10.0, 'tools + MCP(真实) + skills + 调度器', ha='center', fontsize=10, color='gray')

# 用户请求
draw_box(4, 8.8, 6, 0.9, '用户请求\n"分析 data/test_sample.txt 文本报告"', 'lightyellow', 9)

# 调度器
draw_box(4, 7.4, 6, 0.9, 'ExecutionEngine 调度器 (max_concurrency=5)\n提交并行任务 + 依赖编排', 'lightgreen', 9)

# 三个并行任务
draw_box(0.3, 5.2, 3.8, 1.3, 'Task 1: text_stats\n(skill)\n统计文件字符/词/行数', 'lightblue', 8)
draw_box(4.5, 5.2, 5, 1.3, 'Task 2: MCP word_count\n(真实 MCP Server)\n通过 stdio 协议统计单词数', 'lightsalmon', 8)
draw_box(9.9, 5.2, 3.8, 1.3, 'Task 3: calculate\n(tool)\n预计算 chars²=47²', 'lightblue', 8)

# 并行标注
ax.annotate('', xy=(9.8, 5.85), xytext=(0.3, 5.85),
            arrowprops=dict(arrowstyle='<->', color='gray', lw=1, linestyle='dashed'))
ax.text(5, 6.15, '并行执行 (Parallel)', ha='center', fontsize=8, color='gray')

# Task 4
draw_box(3, 2.8, 8, 1.3,
         'Task 4: DeepAgent 综合分析 (串行)\n'
         '工具集: text_stats(skill) + calculate(tool) + MCP echo\n'
         '接收 Task 1/2/3 结果 → 用 MCP echo 确认 → 生成报告',
         'plum', 8)

# 等待标注
ax.text(7, 4.5, '等待 Task 1/2/3 完成', ha='center', fontsize=8, color='gray',
        bbox=dict(boxstyle='round', facecolor='white', edgecolor='gray', alpha=0.8))

# 最终报告
draw_box(4, 1.0, 6, 0.9, '最终分析报告\n"字符数47, 平方2209, MCP确认通过"', 'lightyellow', 9)

# 箭头
draw_arrow(7, 8.8, 7, 8.3)          # 用户→调度器
draw_arrow(5.5, 7.4, 2.2, 6.5)      # 调度器→Task1
draw_arrow(7, 7.4, 7, 6.5)          # 调度器→Task2
draw_arrow(8.5, 7.4, 11.8, 6.5)     # 调度器→Task3
draw_arrow(2.2, 5.2, 4.5, 4.1)      # Task1→Task4
draw_arrow(7, 5.2, 7, 4.1)          # Task2→Task4
draw_arrow(11.8, 5.2, 9.5, 4.1)     # Task3→Task4
draw_arrow(7, 2.8, 7, 1.9)          # Task4→报告

# 图例
ax.text(0.3, 0.2, '■ skill(蓝)  ■ MCP真实Server(橙)  ■ tool(蓝)  ■ DeepAgent(紫)  ■ 调度器(绿)',
        fontsize=8, color='gray')

plt.tight_layout()
output = Path(__file__).parent / "task_orchestration_flow.png"
plt.savefig(output, dpi=150, bbox_inches='tight')
print(f"PNG saved: {output}")
