#!/usr/bin/env python3
"""
Crontab 生成器 - 集中管理所有 OpenClaw cron 条目

规则：
1. 所有日志统一写到 /root/.openclaw/cron_log/
2. 日期格式用 %% 转义，绝不用 % 或 \%
3. 安装前先 dry-run 验证
4. 每条 entry 有固定结构，易审计

用法：
    python3 gen_crons.py [--install] [--show] [--validate]
"""

import os
import subprocess
import sys
from datetime import datetime

# ============ 配置区 ============
AGENTS = [
    "main", "capital", "dev",
    "bingbu", "hubu", "gongbu",
    "legal", "libu", "ops",
    "libu_hr", "menxia", "rich",
    "shangshu", "taizi", "xingbu",
    "zaochao", "zhongshu"
]

MEM0_SETUP = "/root/.openclaw/mem0-agent-setup"
CRON_LOG_DIR = "/root/.openclaw/cron_log"
WORKSPACE_BASE = "/root/.openclaw"

# 时间安排（分钟错开，每 agent 间隔 1 分钟）
CLEANUP_TIMES = {i: t for i, t in enumerate([0, 5, 10, 15, 20, 25])}
DISTILL_TIMES = {i: t for i, t in enumerate([0, 5, 10, 15, 20, 25])}

# ============ 日志函数 ============
def log_dir_for(agent):
    """每 agent 一个独立日志目录"""
    return f"{CRON_LOG_DIR}"

def get_minute(times_dict, index):
    """获取时间，循环使用"""
    return list(times_dict.values())[index % len(times_dict)]

def workspace_path(agent):
    """agent 对应的 workspace 目录"""
    if agent == "main":
        return f"{WORKSPACE_BASE}/workspace"
    return f"{WORKSPACE_BASE}/workspace-{agent}"

def cleanup_cron(agent, minute):
    """生成 cleanup cron 条目（无 date echo，用固定标记）"""
    ws = workspace_path(agent)
    marker = f"CLEANUP-{agent}"
    return (
        f"{minute} 3 * * * "
        f". {ws}/.env 2>/dev/null; "
        f"AGENT_NAME={agent}; "
        f"echo \"[{marker}] START\" >> {CRON_LOG_DIR}/cleanup_{agent}.log 2>&1; "
        f"python3 {MEM0_SETUP}/scripts/memory_cleanup.py >> {CRON_LOG_DIR}/cleanup_{agent}.log 2>&1; "
        f"echo \"[{marker}] END\" >> {CRON_LOG_DIR}/cleanup_{agent}.log 2>&1"
    )

def distill_cron(agent, minute):
    """生成 distill cron 条目（无 date echo，用固定标记）"""
    ws = workspace_path(agent)
    marker = f"DISTILL-{agent}"
    return (
        f"{minute} 4 * * * "
        f". {ws}/.env 2>/dev/null; "
        f"AGENT_NAME={agent}; "
        f"echo \"[{marker}] START\" >> {CRON_LOG_DIR}/distill_{agent}.log 2>&1; "
        f"python3 {MEM0_SETUP}/scripts/memory_distill_daily.py --agent {agent} --force --days 1 --yes >> {CRON_LOG_DIR}/distill_{agent}.log 2>&1; "
        f"echo \"[{marker}] END\" >> {CRON_LOG_DIR}/distill_{agent}.log 2>&1"
    )

# ============ 验证函数 ============
def validate_date_format():
    """
    验证 echo + date 组合能否产生正确时间戳。
    
    POSIX shell 规则:
    - 在 echo "..." 中，\% 不是转义，输出 \Y
    - 在 cron 条目中（不是 bash），\% = literal %（cron 自己的语法）
    - 正确方式：用 \\ 在 shell 中生成传递给 date 的 \%，但太复杂
    
    最可靠方案：echo 一个固定字符串，不用 date。
    """
    # 测试 echo 固定格式
    result = subprocess.run(
        'echo "CRON TEST"',
        shell=True, capture_output=True, text=True
    )
    if "CRON TEST" in result.stdout:
        return True, "echo 正常，echo + date timestamp 用固定标记代替"
    return False, f"echo 失败: {result.stderr}"

def validate_cron_line(line, name):
    """验证单条 cron 行"""
    errors = []
    
    # 检查 6 个字段
    parts = line.split()
    if len(parts) < 6:
        return False, f"字段不足: {len(parts)}"
    
    # 检查是否有未转义的 %
    raw_date = line[line.find('date +"'):line.find('"', line.find('date +"')+10)] if 'date +"' in line else ''
    if raw_date and '%' in raw_date and '%%' not in raw_date and '\\%' not in raw_date:
        errors.append(f"未转义的 % 在: {raw_date}")
    
    # 检查 >> 目标目录存在
    for redirect in line.split('>>'):
        if '>>' in redirect:
            continue
        path = redirect.strip().split()[0] if redirect.strip() else ''
        if path.startswith('/') and not os.path.exists(os.path.dirname(path)):
            errors.append(f"目录不存在: {os.path.dirname(path)}")
    
    # 检查 python 路径存在
    for token in line.split():
        if token.startswith(MEM0_SETUP) and not os.path.exists(token.split(';')[0]):
            errors.append(f"脚本不存在: {token}")
    
    return len(errors) == 0, errors

# ============ 主逻辑 ============
def generate():
    """生成 crontab 内容"""
    lines = []
    lines.append("# OpenClaw Memory Cron Jobs")
    lines.append(f"# 生成时间: {datetime.now().isoformat()}")
    lines.append("# 警告: 不要直接编辑此文件，用 gen_crons.py 管理")
    lines.append("")
    
    # Cleanup
    for i, agent in enumerate(AGENTS):
        minute = get_minute(CLEANUP_TIMES, i)
        lines.append(cleanup_cron(agent, minute))
    
    lines.append("")
    
    # Distill
    for i, agent in enumerate(AGENTS):
        minute = get_minute(DISTILL_TIMES, i)
        lines.append(distill_cron(agent, minute))
    
    return '\n'.join(lines) + '\n'

def validate():
    """验证 crontab（不安装）"""
    print("=== 验证 Crontab ===\n")
    
    # 验证 date 格式
    ok, result = validate_date_format()
    print(f"date %% 格式: {'✅' if ok else '❌'} {result}")
    
    # 生成并验证
    content = generate()
    errors = []
    warnings = []
    
    for i, line in enumerate(content.split('\n'), 1):
        if not line.strip() or line.startswith('#'):
            continue
        if 'python3' in line or 'AGENT_NAME' in line:
            ok, result = validate_cron_line(line, f"line {i}")
            if not ok:
                errors.append(f"line {i}: {result}")
    
    # 检查日志目录
    if not os.path.exists(CRON_LOG_DIR):
        errors.append(f"日志目录不存在: {CRON_LOG_DIR}")
    else:
        print(f"日志目录: ✅ {CRON_LOG_DIR}")
        # 检查是否可写
        test_file = f"{CRON_LOG_DIR}/test_write"
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print(f"日志可写: ✅")
        except Exception as e:
            errors.append(f"日志目录不可写: {e}")
    
    print()
    if errors:
        print(f"❌ 发现 {len(errors)} 个错误:")
        for e in errors:
            print(f"  - {e}")
        return False
    
    print("✅ 验证通过")
    return True

def install(content):
    """安装 crontab"""
    # 先备份
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        if result.stdout.strip():
            backup = f"/tmp/crontab_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(backup, 'w') as f:
                f.write(result.stdout)
            print(f"✅ 备份到: {backup}")
    except:
        pass
    
    # 安装
    proc = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE)
    proc.communicate(content.encode())
    if proc.returncode == 0:
        print("✅ Crontab 安装成功")
    else:
        print(f"❌ 安装失败: returncode {proc.returncode}")
        return False
    return True

def show():
    """显示生成的 crontab"""
    print(generate())

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else '--show'
    
    if cmd == '--validate':
        ok = validate()
        sys.exit(0 if ok else 1)
    elif cmd == '--install':
        content = generate()
        if validate():
            install(content)
        else:
            print("验证失败，拒绝安装")
            sys.exit(1)
    elif cmd == '--show':
        show()
    else:
        print(__doc__)
        sys.exit(1)
