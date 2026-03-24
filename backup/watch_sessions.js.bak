#!/usr/bin/env node
/**
 * Session Directory Watcher
 * 
 * 监听 sessions 目录变化，自动同步新对话到 Mem0
 * 
 * 用法: node scripts/watch_sessions.js [agentId]
 * 
 * 支持的 agent: main, capital, dev, legal, ops 等
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const AGENT_ID = process.argv[2] || 'main';
const SESSIONS_DIR = `/root/.openclaw/agents/${AGENT_ID}/sessions`;
const WATCH_INTERVAL = 5000; // 每5秒检查一次

// 记录已处理的文件
const processedFiles = new Set();

// 获取所有 session 文件
function getSessionFiles() {
  if (!fs.existsSync(SESSIONS_DIR)) {
    return [];
  }
  return fs.readdirSync(SESSIONS_DIR)
    .filter(f => f.endsWith('.jsonl') && !f.includes('.deleted.'));
}

// 同步单个文件到 Mem0
function syncFile(filepath) {
  if (processedFiles.has(filepath)) {
    return 0;
  }
  
  const { execSync } = require('child_process');
  
  // 解析文件
  const content = fs.readFileSync(filepath, 'utf-8');
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
        // 新格式: System: [...] + Conversation info + Sender info + 真实消息
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
    processedFiles.add(filepath);
    return 0;
  }
  
  // 过滤有效消息
  const validMessages = messages.filter(m => 
    m.user.length >= 5 && 
    !m.user.startsWith('System:') && 
    !m.user.startsWith('Read HEARTBEAT')
  );
  
  if (validMessages.length === 0) {
    processedFiles.add(filepath);
    return 0;
  }
  
  // 同步到 Mem0
  const messagesJson = JSON.stringify(validMessages.slice(0, 10));
  
  try {
    const result = execSync(
      `AGENT_NAME=${AGENT_ID} python3 /root/.openclaw/workspace/scripts/sync_to_mem0.py`,
      { 
        encoding: 'utf-8', 
        timeout: 30000,
        input: messagesJson,
        env: { ...process.env, AGENT_NAME: AGENT_ID }
      }
    );
    
    if (result.includes('DONE:')) {
      const count = parseInt(result.split('DONE:')[1]);
      processedFiles.add(filepath);
      return count;
    }
  } catch (e) {
    // 静默失败
  }
  
  return 0;
}

// 检查并同步
function checkAndSync() {
  const files = getSessionFiles();
  
  for (const file of files) {
    const filepath = path.join(SESSIONS_DIR, file);
    
    // 检查文件是否有新内容（文件大小变化）
    try {
      const stats = fs.statSync(filepath);
      const fileKey = `${filepath}:${stats.size}`;
      
      if (!processedFiles.has(fileKey)) {
        const added = syncFile(filepath);
        if (added > 0) {
          console.log(`[${new Date().toISOString()}] ${AGENT_ID}: +${added} 条 -> ${file}`);
        }
        // 记录文件大小
        processedFiles.add(fileKey);
      }
    } catch (e) {}
  }
}

// 主函数
function main() {
  console.log(`=== Session Watcher ===`);
  console.log(`Agent: ${AGENT_ID}`);
  console.log(`Watching: ${SESSIONS_DIR}`);
  console.log(`Interval: ${WATCH_INTERVAL}ms`);
  console.log('');
  
  if (!fs.existsSync(SESSIONS_DIR)) {
    console.error(`ERROR: Sessions directory not found: ${SESSIONS_DIR}`);
    process.exit(1);
  }
  
  // 初始化：处理现有文件
  console.log('Initial scan...');
  const files = getSessionFiles();
  console.log(`Found ${files.length} session files`);
  
  // 标记所有现有文件为已处理（只监控新内容）
  for (const file of files) {
    const filepath = path.join(SESSIONS_DIR, file);
    try {
      const stats = fs.statSync(filepath);
      processedFiles.add(`${filepath}:${stats.size}`);
    } catch (e) {}
  }
  
  console.log('Watching for new messages...\n');
  
  // 定期检查
  setInterval(checkAndSync, WATCH_INTERVAL);
}

main();
