#!/usr/bin/env node
/**
 * Session Directory Watcher - 增强版
 * 
 * 改进：
 * 1. 文件删除检测：检测到 session 文件消失时，立即尝试读取并同步
 * 2. Pre-reset 触发器：检测到 /tmp/.pre_reset_sync.{agent} 文件时，执行全量同步
 * 3. 更快轮询：发现变化时自动加速轮询
 * 
 * 用法: node scripts/watch_sessions.js [agentId]
 */

const fs = require('fs');
const path = require('path');

const AGENT_ID = process.argv[2] || 'main';
const SESSIONS_DIR = `/root/.openclaw/agents/${AGENT_ID}/sessions`;
const BASE_INTERVAL = 5000;        // 基础轮询间隔
const FAST_INTERVAL = 500;         // 加速轮询间隔（检测到变化后）
const FAST_DURATION = 10000;       // 加速持续时间
const PRE_RESET_FILE = `/tmp/.pre_reset_sync.${AGENT_ID}`;

let pollInterval = BASE_INTERVAL;
let lastChangeTime = 0;

// 记录已处理的文件：filepath -> {size, mtime, deleted}
// deleted=true 表示文件已被删除但尚未处理
const fileStates = new Map();

// 从 .env 加载环境变量
function loadEnv() {
  const env = { ...process.env, AGENT_NAME: AGENT_ID };
  try {
    const envContent = fs.readFileSync('/root/.openclaw/mem0-agent-setup/.env', 'utf-8');
    for (const line of envContent.split('\n')) {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
        const [key, ...rest] = trimmed.split('=');
        if (key.trim() === 'OPENAI_API_KEY') {
          env[key.trim()] = rest.join('=').trim();
        }
      }
    }
  } catch (e) {}
  return env;
}

// 获取所有 session 文件
function getSessionFiles() {
  if (!fs.existsSync(SESSIONS_DIR)) {
    return [];
  }
  return fs.readdirSync(SESSIONS_DIR)
    .filter(f => f.endsWith('.jsonl') && !f.includes('.deleted.'));
}

// 同步单个文件到 Mem0
function syncFile(filepath, isUrgent = false) {
  // 尝试读取文件内容（即使已被删除，如果 inode 还在就能读到）
  let content;
  try {
    content = fs.readFileSync(filepath, 'utf-8');
  } catch (e) {
    // 文件真的没了（inode 已释放），无法恢复
    return -1;
  }
  
  const lines = content.trim().split('\n');
  let messages = [];
  let currentUserMsg = null;
  
  for (const line of lines) {
    if (!line.trim()) continue;
    
    try {
      const obj = JSON.parse(line);
      if (obj.type !== 'message' || !obj.message) continue;
      
      const msg = obj.message;
      const role = msg.role;
      
      let text = '';
      if (msg.content && Array.isArray(msg.content)) {
        for (const c of msg.content) {
          if (c.type === 'text' && c.text && c.text.trim()) {
            text = c.text.trim();
            break;
          }
        }
      }
      
      if (role === 'user' && text.length > 20) {
        let userMsg = text;
        if (text.startsWith('System:')) {
          const senderMatch = text.match(/Sender \(untrusted metadata\):[\s\S]+?\n\n([\s\S]+)$/);
          if (senderMatch && senderMatch[1] && senderMatch[1].trim().length > 0) {
            userMsg = senderMatch[1].trim();
          }
        }
        if (userMsg.length > 0) {
          currentUserMsg = userMsg.slice(0, 500);
        }
      } else if (role === 'assistant' && currentUserMsg && text.length > 0) {
        messages.push({ 
          user: currentUserMsg.slice(0, 500), 
          assistant: text.slice(0, 500) 
        });
        currentUserMsg = null;
      }
    } catch (e) {}
  }
  
  if (messages.length === 0) {
    return 0;
  }
  
  // 过滤有效消息
  const validMessages = messages.filter(m => 
    m.user.length >= 5 && 
    !m.user.startsWith('System:') && 
    !m.user.startsWith('Read HEARTBEAT')
  );
  
  if (validMessages.length === 0) {
    return 0;
  }
  
  // 重要：reset 文件同步全部消息；普通文件同步最后 10 条
  const isResetFile = filepath.includes('.reset.');
  const messagesToSync = isResetFile ? validMessages : validMessages.slice(-10);
  const messagesJson = JSON.stringify(messagesToSync);
  
  const env = loadEnv();
  
  try {
    const result = require('child_process').execSync(
      `python3 /root/.openclaw/mem0-agent-setup/scripts/sync_to_mem0.py`,
      { 
        encoding: 'utf-8', 
        timeout: 30000,
        input: messagesJson,
        env: env
      }
    );
    
    if (result.includes('DONE:')) {
      const count = parseInt(result.split('DONE:')[1]);
      if (isUrgent) {
        console.log(`[${new Date().toISOString()}] [URGENT] ${AGENT_ID}: +${count} 条 -> ${path.basename(filepath)} (${isResetFile ? 'full' : 'last10'})`);
      }
      return count;
    }
  } catch (e) {
    // 静默失败
  }
  
  return 0;
}

// 全量同步：同步所有已知文件（用于 pre-reset 触发）
function syncAllFiles(urgent = false) {
  const files = getSessionFiles();
  let total = 0;
  
  for (const file of files) {
    const filepath = path.join(SESSIONS_DIR, file);
    const added = syncFile(filepath, urgent);
    if (added > 0) total += added;
  }
  
  // 也尝试同步那些已被删除但可能还有 inode 的文件
  for (const [filepath, state] of fileStates) {
    if (state.deleted) {
      const added = syncFile(filepath, urgent);
      if (added > 0) total += added;
    }
  }
  
  return total;
}

// 检查 pre-reset 触发器
function checkPreResetTrigger() {
  if (fs.existsSync(PRE_RESET_FILE)) {
    console.log(`[${new Date().toISOString()}] [PRE-RESET] 检测到重置触发器，执行全量同步...`);
    const count = syncAllFiles(true);
    console.log(`[${new Date().toISOString()}] [PRE-RESET] 完成: ${count} 条消息已同步`);
    try {
      fs.unlinkSync(PRE_RESET_FILE);
      console.log(`[${new Date().toISOString()}] [PRE-RESET] 触发器已清除`);
    } catch (e) {}
    return true;
  }
  return false;
}

// 主检查函数
function checkAndSync() {
  // 1. 检查 pre-reset 触发器
  checkPreResetTrigger();
  
  // 2. 检测文件变化
  const files = getSessionFiles();
  const currentFiles = new Set(files);
  
  let hasChanges = false;
  
  // 2a. 检查现有文件的变化
  for (const file of files) {
    const filepath = path.join(SESSIONS_DIR, file);
    
    try {
      const stats = fs.statSync(filepath);
      const state = fileStates.get(filepath);
      
      if (!state) {
        // 新文件
        fileStates.set(filepath, { size: stats.size, mtime: stats.mtimeMs, deleted: false });
        const added = syncFile(filepath);
        if (added > 0) {
          console.log(`[${new Date().toISOString()}] ${AGENT_ID}: +${added} 条 -> ${file}`);
          hasChanges = true;
        }
      } else if (state.size !== stats.size || state.mtime !== stats.mtimeMs) {
        // 文件有变化
        fileStates.set(filepath, { size: stats.size, mtime: stats.mtimeMs, deleted: false });
        const added = syncFile(filepath);
        if (added > 0) {
          console.log(`[${new Date().toISOString()}] ${AGENT_ID}: +${added} 条 -> ${file} [updated]`);
          hasChanges = true;
        }
      }
    } catch (e) {
      // 文件读取失败
    }
  }
  
  // 2b. 检测被删除的文件（Session Reset）
  // 如果一个之前存在的文件现在不见了，说明发生了 session reset
  for (const [filepath, state] of fileStates) {
    const basename = path.basename(filepath);
    if (!currentFiles.has(basename) && !state.deleted) {
      console.log(`[${new Date().toISOString()}] [RESET DETECTED] 检测到文件消失: ${basename}`);
      // 文件被删除前可能还有内容没同步，尝试紧急同步
      fileStates.set(filepath, { ...state, deleted: true });
      const added = syncFile(filepath, true); // urgent=true
      if (added > 0) {
        console.log(`[${new Date().toISOString()}] [RESET RECOVERED] 恢复 ${added} 条消息 from ${basename}`);
        hasChanges = true;
      } else {
        console.log(`[${new Date().toISOString()}] [RESET] ${basename} 无法恢复（内容可能已丢失）`);
      }
    }
  }
  
  // 3. 加速轮询：如果有变化，加速轮询一段时间
  if (hasChanges) {
    lastChangeTime = Date.now();
    if (pollInterval !== FAST_INTERVAL) {
      pollInterval = FAST_INTERVAL;
      console.log(`[${new Date().toISOString()}] [SPEED UP] 切换到快速轮询 (${FAST_INTERVAL}ms)`);
    }
  } else if (Date.now() - lastChangeTime > FAST_DURATION && pollInterval !== BASE_INTERVAL) {
    pollInterval = BASE_INTERVAL;
    console.log(`[${new Date().toISOString()}] [SLOW DOWN] 恢复基础轮询 (${BASE_INTERVAL}ms)`);
  }
}

// 主函数
function main() {
  console.log(`=== Session Watcher (增强版) ===`);
  console.log(`Agent: ${AGENT_ID}`);
  console.log(`Watching: ${SESSIONS_DIR}`);
  console.log(`Base Interval: ${BASE_INTERVAL}ms`);
  console.log(`Pre-reset trigger: ${PRE_RESET_FILE}`);
  console.log('');
  
  if (!fs.existsSync(SESSIONS_DIR)) {
    console.error(`ERROR: Sessions directory not found: ${SESSIONS_DIR}`);
    process.exit(1);
  }
  
  // 初始化：扫描现有文件
  console.log('Initial scan...');
  const files = getSessionFiles();
  console.log(`Found ${files.length} session files`);
  
  for (const file of files) {
    const filepath = path.join(SESSIONS_DIR, file);
    try {
      const stats = fs.statSync(filepath);
      fileStates.set(filepath, { size: stats.size, mtime: stats.mtimeMs, deleted: false });
    } catch (e) {}
  }
  
  console.log('Watching for changes...\n');
  
  // 立即执行一次同步（包括 pre-reset 检查）
  checkAndSync();
  
  // 定期检查
  setInterval(checkAndSync, pollInterval);
  
  // 动态调整轮询间隔
  setInterval(() => {
    if (pollInterval !== BASE_INTERVAL) {
      checkAndSync();
    }
  }, pollInterval);
}

main();
