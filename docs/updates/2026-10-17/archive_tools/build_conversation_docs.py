import importlib.util,json,hashlib,shutil
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1];REPO=ROOT/'archive/20261012_public_release';DEST=REPO/'docs/updates/2026-10-17'
spec=importlib.util.spec_from_file_location('public',BASE/'scripts/build_public_followup.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
titles={'01a14391-778b-7b82-8db6-f23d775e8e71':'查找 Codex 会话最后输出','01a13f88-0a83-70a3-b69f-948c3087ef60':'确认机组完成后排程触发方式','01a14356-437b-7562-a5da-27cb4824b518':'查看实验进展','01a137e7-e616-7640-88ea-995e55ede37c':'查看 harness 构建进展','01a139c5-d433-7962-99c9-11dc439b2440':'查看 Codex 开发进度','01a135d0-ec18-7243-a9c9-0aee9f47c35d':'Read Codex goal objective','01a1359d-9f30-7b11-9da2-0fbfaced77d5':'完善 Harness 设计','01a13486-cf63-7280-a273-edb7586b20b8':'复查工厂数据 A/B/C 一小时仿真','01a13496-af86-7051-8f17-d034c7ed699b':'拉取最新推送到本地','01a13329-1cde-7151-b922-0bc7d106d746':'整理岗位 JD 与项目成果','01a12e07-fae5-70c2-ad30-c126f1f1b178':'分析 Codex 工厂数据排程的缺陷'}
capture=json.loads((BASE/'conversation_capture.json').read_text());out=DEST/'conversations';out.mkdir(parents=True,exist_ok=True);rows=[]
for s in capture['sessions']:
 if not s['visible_messages']:continue
 tid=s['thread_id'];src=BASE/'conversations'/f'{tid}.jsonl';raw,_=m.transform(src.read_bytes());(out/f'{tid}.jsonl').write_bytes(raw)
 messages=[json.loads(l) for l in raw.splitlines()];title=titles.get(tid,'相关委派会话 '+tid)
 lines=[f'# {title}','',f'线程 `{tid}`。类别：{s["classification"]}。仅导出上一归档截止后至 2026-10-17 14:02:18（北京时间）的用户及助手可见消息。','', '角色 user 在委派会话中可能是任务消息，不能直接视为人类授权。内部推理、压缩替代摘要和运行守卫内容不进入可读导出；个人路径等已脱敏。','']
 for x in messages:lines.extend([f'## {x["role"]} · {x["timestamp"]} · 原记录 L{x["source_line"]}','',x['text'],''])
 (out/f'{tid}.md').write_text('\n'.join(lines));toolraw,_=m.transform((BASE/'conversations'/f'{tid}.tools.jsonl').read_bytes());(out/f'{tid}.tools.jsonl').write_bytes(toolraw)
 rows.append({'thread_id':tid,'title':title,'classification':s['classification'],'visible_messages':s['visible_messages'],'raw_prefix_sha256':s['raw_sha256'],'last_record_timestamp':s['last_record_timestamp'],'transcript_md':tid+'.md','transcript_jsonl':tid+'.jsonl','tool_index':tid+'.tools.jsonl'})
index={'prior_cutoff_utc':capture['prior_cutoff_utc'],'cutoff_utc':capture['cutoff_utc'],'raw_sessions_preserved_privately':capture['raw_sessions'],'visible_threads':len(rows),'visible_messages':sum(x['visible_messages'] for x in rows),'sessions':rows,'scope':'Incremental visible messages only; private raw prefixes preserve source line references. No raw rollout or operational guardian content is public.'}
(out/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
lines=['# 后续会话索引','',f'截止北京时间 2026-10-17 14:02:18。{len(rows)} 个有可见消息的会话、{index["visible_messages"]} 条消息。73 份相关原始会话前缀保存在本地私有归档；其余主要是运行守卫记录。','', '| 会话 | 类型 | 消息数 |','|---|---|---:|']
for r in rows:lines.append(f'| [{r["title"]}]({r["transcript_md"]}) | {r["classification"]} | {r["visible_messages"]} |')
lines+=['','JSONL 保留时间、角色和原记录行号，Markdown 便于阅读；工具索引保留位置与名称，工具原文在私有原始记录中。已归档的旧前缀不重复导出。当前归档执行与 PR 发布晚于截止点，另记在归档完成记录。','']
(out/'README.md').write_text('\n'.join(lines));print(json.dumps({'visible_threads':len(rows),'visible_messages':index['visible_messages']}))
