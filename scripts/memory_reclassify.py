#!/usr/bin/env python3
"""
批量重分类 - 使用 Qdrant set_payload 只更新 data 字段
"""
import os, sys, re, time
from qdrant_client import QdrantClient
from openai import OpenAI

os.environ['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', '')
API_KEY = os.environ.get('OPENAI_API_KEY', '')
if not API_KEY:
    print("ERROR: set OPENAI_API_KEY env first"); sys.exit(1)

QDRANT_HOST, QDRANT_PORT = 'localhost', 6333
COLLECTION = 'mem0_main'
BATCH_SIZE = 10
BATCH_DELAY = 3

def llm_classify(text: str) -> dict:
    prompt = f"""对以下消息分类：

"{text[:400]}"

评分(1-5): 5=核心/名字/承诺 4=重要偏好 3=一般 2=临时 1=无价值
类型: episodic=事件 semantic=偏好/习惯 procedural=步骤

只回JSON: {{"score": 数字, "type": "类型"}}"""
    try:
        client = OpenAI(api_key=API_KEY, base_url='https://api.siliconflow.cn/v1')
        resp = client.chat.completions.create(
            model='Qwen/Qwen2.5-7B-Instruct',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1
        )
        text_resp = resp.choices[0].message.content.strip()
        s = re.search(r'"score"\s*:\s*(\d)', text_resp)
        t = re.search(r'"type"\s*:\s*"(episodic|semantic|procedural)"', text_resp)
        return {'score': int(s.group(1)) if s else 3, 'type': t.group(1) if t else 'semantic'}
    except Exception as e:
        print(f"[WARN] LLM: {e}", file=sys.stderr)
        return {'score': 3, 'type': 'semantic'}

def needs_prefix(data: str) -> bool:
    return not bool(re.search(r'\[(episodic|semantic|procedural)\]\[score:\d+\]', data))

def main():
    client = QdrantClient(url=f'http://{QDRANT_HOST}:{QDRANT_PORT}')

    all_to_classify = []
    offset = None
    while True:
        result = client.scroll(collection_name=COLLECTION, limit=200, offset=offset)
        if not result[0]:
            break
        for p in result[0]:
            data = p.payload.get('data', '')
            if needs_prefix(data):
                all_to_classify.append({
                    'id': p.id,
                    'data': data,
                    'payload': dict(p.payload)
                })
        offset = result[1]
        if offset is None:
            break

    total = len(all_to_classify)
    print(f"需重分类: {total} 条")

    if total == 0:
        print("✅ 全部已分类")
        return

    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    processed = 0

    for batch_idx in range(total_batches):
        s = batch_idx * BATCH_SIZE
        e = min(s + BATCH_SIZE, total)
        batch = all_to_classify[s:e]

        print(f"\n[{batch_idx+1}/{total_batches}] 处理 {s+1}-{e}...")

        for record in batch:
            data = record['data']
            clean = re.sub(r'^\[.*?\]\[score:\d+\]\s*', '', data).strip()
            if not clean:
                continue

            cls = llm_classify(clean)
            new_data = f"[{cls['type']}][score:{cls['score']}] {clean}"

            # 只更新 data 字段，保留其他字段
            client.set_payload(
                collection_name=COLLECTION,
                payload={'data': new_data},
                points=[str(record['id'])],
                wait=True
            )
            print(f"  ✅ {str(record['id'])[:8]}... [{cls['type']}][score:{cls['score']}]")
            time.sleep(0.3)

        processed += len(batch)
        print(f"  本批完成: {len(batch)}/{len(batch)} ✅")

        if batch_idx < total_batches - 1:
            print(f"  ⏳ 等待 {BATCH_DELAY}s...")
            time.sleep(BATCH_DELAY)

    print(f"\n🎉 完成! 已处理 {processed}/{total} 条")

if __name__ == '__main__':
    main()
