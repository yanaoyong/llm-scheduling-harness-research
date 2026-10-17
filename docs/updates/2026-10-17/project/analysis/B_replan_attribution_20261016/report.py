"""Read-only queue corroboration and human report; no runtime imports."""
from analyze import Evidence, SOURCE, OUT, sha
from collections import Counter
import json


def queue_witness():
    run = SOURCE / 'runs/singleton_2403__filter_projection'
    frozen = SOURCE / 'workspace/src/smt_fullfab'
    tracked = [run / 'events.sqlite3', run / 'evidence_manifest.json',
               SOURCE / 'completion_verification.json', frozen / 'plan_delta.py', frozen / 'environment.py']
    before = {str(p): sha(p) for p in tracked}
    seal = json.loads((SOURCE / 'completion_verification.json').read_text())
    assert before[str(run / 'evidence_manifest.json')] == seal['rows'][1]['evidence_sha256']
    e = Evidence(run)
    contexts = e.records('contexts')
    candidates = e.records('candidates')
    commits = sorted(e.records('commits').values(), key=lambda c: c['actual_revision'])
    ids = {'d132-w460', 'd132-w468'}
    history, changes = [], []
    for c in commits:
        ca = candidates[c['candidate_ref']]
        ctx = contexts[ca['context_ref']]
        old = {t['id']: t for t in ctx['base_plan']['tasks']}
        tasks = [t for t in ca['compiled']['plan']['tasks'] if t['id'] in ids]
        if not tasks:
            continue
        evidence = ca['compiled']['evidence']
        entry = {'time': c['time'], 'context_ref': ca['context_ref'], 'candidate_ref': c['candidate_ref'],
                 'tasks': tasks, 'added_ids': [x for x in evidence['added_task_ids'] if x in ids],
                 'replaced_ids': [x for x in evidence['replaced_task_ids'] if x in ids],
                 'cancelled_ids': [x for x in evidence['cancelled_task_ids'] if x in ids]}
        history.append(entry)
        for t in tasks:
            if t['id'] in entry['replaced_ids']:
                prior = old[t['id']]
                diff = {k: {'before': prior.get(k), 'after': t.get(k)}
                        for k in prior.keys() | t.keys() if prior.get(k) != t.get(k)}
                assert set(diff) == {'not_before'}
                assert prior['not_before'] < ctx['time'] < t['not_before']
                changes.append({'time': ctx['time'], 'id': t['id'], 'diff': diff,
                                'candidate_ref': c['candidate_ref'], 'context_ref': ca['context_ref']})
    dispatches = []
    for seq, ref in e.db.execute('SELECT seq,object_ref FROM physical ORDER BY seq'):
        event = e.get(ref)
        if event.get('plan_task_id') in ids and event['kind'] == 'dispatch':
            dispatches.append({'physical_seq': seq, 'object_sha256': ref, 'event': event})
    feedback = e.records('feedback').values()
    triggers = [f['to'] for f in feedback if f['stop_reason']['reason'] == 'uncovered_demand']
    assert len(triggers) == 23
    assert len(dispatches) == 1 and dispatches[0]['event']['plan_task_id'] == 'd132-w460'
    assert dispatches[0]['event']['time'] == 2686.6817943212754
    assert dispatches[0]['event']['time'] not in triggers
    assert len(changes) == 10 and len(set(x['time'] for x in changes)) == 6
    last_context = max(contexts.values(), key=lambda c: c['time'])
    assert last_context['time'] == 2703
    machine927 = next(m for m in last_context['problem']['machines'] if m['machine'] == 927)
    assert machine927['currently_busy']
    assert all(not row['cancelled_ids'] for row in history)
    after = {str(p): sha(p) for p in tracked}
    assert before == after
    result = {'source_run': str(run), 'source_files_sha256': before, 'history': history,
              'changes': changes, 'dispatches': dispatches, 'demand_trigger_times': triggers,
              'end_machine_927': machine927, 'end_time': last_context['time'],
              'summary': {'replacement_rounds': 6, 'task_replacements': 10, 'demand_triggers': 23,
                          'source_files_unchanged': True, 'content_objects_verified': len(e.refs)},
              'limits': ['The ten replacements occurred in six existing planning rounds; extra model calls caused by maintenance are not proven.',
                         'The observed w460 dispatch predates no required condition and occurs after its last not_before; no artificial delay is shown.',
                         'w468 is pending at the evaluation boundary while its machine is busy; this is not evidence of a lost task.']}
    (OUT / 'queue_witness.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'queue_source_objects.json').write_text(json.dumps(e.refs, sort_keys=True, indent=2) + '\n')
    e.db.close()
    return result


def write_report(data, witness):
    rows = data['rows']
    s = data['summary']
    letters = {'ready_backlog_machine_release': 'A', 'known_successor_no_observed_branch': 'B',
               'sampled_target_realized': 'C', 'sampled_predecessor_skipped': 'D'}
    def event_description(d):
        parts = []
        for ev in d['relevant_actual_lot_events']:
            if ev['kind'] == 'operation_complete':
                parts.append(f"工序{ev['step']}完工")
            elif ev['kind'] == 'skip':
                parts.append(f"跳过{ev['step']}")
            elif ev['kind'] == 'ready':
                parts.append(f"工序{ev['step']}就绪")
        return '→'.join(parts) or '已有ready任务；机台占用结束后出现合法派工缺口'
    lines = [
        '基线 24 次重排逐次归因（只读分析，不启动新实验）',
        '',
        '对象：B_context_2x2_20261016 的 baseline，公共窗口 t=2403→2703。',
        '这里的24次是24个 uncovered_demand 停止/重新规划点，不是24次模型调用。',
        '全程有25份已提交计划；最后在t=2703结束的periodic_replan是评估边界，不纳入这24次。',
        '表中所有时间均为仿真秒，不是模型或本地处理的实际墙钟耗时。',
        '',
        '主要结论',
        '1. 7次已有ready任务等设备释放，是最明确的提前排队候选；4次是公开可见的后继工序变为ready，具备条件预排的可能；13次涉及抽样保留或跳步，真实分支必须等事件确认。',
        '2. “执行必须等新事件”不等于“必须重新调用模型”。7+4=11是应优先核查的提前覆盖候选数，不是已经证明能省掉11次重排。13次分支类也不能一概判成不可避免的模型重排。',
        '3. 27个后续实际派工的operation_id在紧邻上一轮公共目录中全部存在，且当时已列出后来选择的合法机台。没有发现必须等新实体到达才能知道任务身份的案例。',
        '4. 基线24个触发点都没有剩余已排任务；没有取消、替换、hold或计划失效，计划还剩56.462～119.913仿真秒。现有证据支持“覆盖没有预先建立”，不支持“队列任务丢失”或“有效期太短”。',
        '5. 已有filter_projection轨迹提供一条实际提前覆盖证据：w460:31:1在2550.910已入队，2686.682自动派工，未出现基线第21次对应的模型重排。该组因此是23次需求触发；但全组模型调用并未更少，不能把单条覆盖效果说成总成本改善。',
        '6. 同一预排队列还暴露了维护负担：两项等待任务在6轮已有重排中共被替换10次，仅更新not_before。没有证据证明这10次替换额外触发模型，也未观察到w460被这些时间改写延误。',
        '',
        '分类口径',
        'A：上一轮conditional=false，任务已就绪，所选机台仍忙；可明确指定任务并等待设备真实可用。',
        'B：上一轮已有后继身份、资格和条件状态；本次因前序完工变为ready，因果转换中未观察到抽样跳步。不是对所有未来分支的确定性保证。',
        'C：目标工序本身sampling_percent<100，本次抽样后实际保留；执行前必须确认该工序存在。预排该工序可能在另一条轨迹被skip并失效。',
        'D：目标之前的抽样工序被skip，后继因而提早变为ready；上一轮可知候选路径，但不能预知抽样结果。预排后继可能在本条轨迹生效；不等于当前接口已支持完整if/else分支。',
        '',
        '逐次总表（格式：编号 | 上轮时间→触发时间 | 推进秒 | 分类 | 实际后续任务→机台 | 触发归因）',
    ]
    for r in rows:
        ds = r['operation_details']
        tasks = '; '.join(f"{d['prior_public_operation']['operation_id']}→{d['task']['machine']}" for d in ds)
        cause = event_description(ds[0])
        if r['category'] == 'sampled_target_realized':
            cause += f"；目标抽样率{ds[0]['prior_public_operation']['sampling_percent']:g}%"
        if r['category'] == 'sampled_predecessor_skipped':
            cause += '；前序抽样率' + ','.join(f"{p['step']}:{p['sampling_percent']:g}%" for p in ds[0]['prior_public_predecessors'])
        lines.append(f"{r['number']:02} | {r['prior_decision_time']:.3f}→{r['trigger_time']:.3f} | {r['advanced_seconds']:.3f} | {letters[r['category']]} | {tasks} | {cause}")
    lines += ['', '逐次证据与能否提前覆盖']
    for r in rows:
        lines += ['', f"第{r['number']:02}次：{data['summary']['category_labels'][r['category']]}",
                  f"上一轮 context={r['prior_context_ref']}；已提交 candidate={r['prior_candidate_ref']}",
                  f"下一轮 context={r['after_context_ref']}；实际派工 candidate={r['next_candidate_ref']}",
                  f"原始physical事件区间（Python切片）=[{r['feedback']['event_start']},{r['feedback']['event_end']})；完整内容见attribution.json rows[{r['number']-1}]。"]
        for d in r['operation_details']:
            op, m = d['prior_public_operation'], d['prior_public_machine']
            shown = d['shown_with_current_critical_fields_in_prior_prompts']
            history = d['shown_with_different_critical_fields_in_prior_prompts']
            visibility = ('保存的上一轮请求中有当前8项关键字段，调用序号=' + ','.join(str(x['attempt']) for x in shown)) if shown else (
                '上一轮请求有历史完整记录，但关键字段与当前不同：' + json.dumps(history[0]['matches'][0]['different_fields'],ensure_ascii=False) if history else '未匹配到上一轮请求中的完整8项关键字段；不能把目录可查当作模型已看见')
            lines += [f"任务 {op['operation_id']}，family={op['family']}，选择机台={m['machine']}，该机台已在上一轮eligible_machines中。",
                      f"上一轮公开事实：conditional={op['conditional']}，release_time={op['release_time']:.6f}，sampling={op['sampling_percent']:g}%；机台busy={m['currently_busy']}，available_at={m['available_at']:.6f}。",
                      '实际事件：' + event_description(d) + '。', '事实呈现：' + visibility + '。']
            if r['category'] == 'ready_backlog_machine_release':
                lines.append('判断：任务本身已就绪，只须等设备真实可用；是上一轮明确多排一个任务的候选。名义available_at并非承诺释放时刻，不能据此硬编码实际开工。')
            elif r['category'] == 'known_successor_no_observed_branch':
                lines.append('判断：可讨论明确后继的条件预排；实际启动仍须前序完成及lot/machine ready。静态身份、资格和批量检查通过，不代表已验证反事实计划的全过程与质量。')
            else:
                lines.append('判断：抽样分支必须等运行事件确认；上一轮能表达已知候选后继，但不能假装已知保留或跳步。是否能减少模型重排还取决于条件承诺、失效与队首等待语义。')
        q = r['queue_audit']
        lines.append(f"队列检查：上一轮新计划{q['previous_plan_task_count']}项均已派工；触发时剩余0项，继承未派任务0项，取消/替换/hold/失效均0；有效期还剩{q['plan_validity_remaining_seconds']:.3f}秒。")
    lines += [
        '', '事实目录、实际呈现与模型选择的区别',
        '27个后续派工任务在上一轮公开目录全部可查询。但严格匹配operation_id、eligible_machines、conditional、release_time、predecessor_ids、sampling_percent、rework_percent、qualification_basis这8项关键字段，只有5个任务在上一轮实际保存的请求中呈现当前值，另1个仅呈现历史记录。',
        '5个当前记录分布在第10、11、24次；第11次的w280另有历史记录，仅release_time不同。只有第10次存在上一轮read_entities直接返回该任务实体的记录。',
        '这是事实呈现层的证据，不是模型注意力或理解程度的测量；摘要或字符串里出现任务ID不等同于呈现完整资格/依赖。',
        '因此暂不能把“一次只新增一个任务”唯一归因于模型规划能力。默认呈现与查询多围绕当前缺口，未来可排候选可能在目录里却未被带入；第10、11次则说明“有部分事实可见”本身也不保证模型会扩大覆盖。',
        '', '队列维护核查与现有跨组见证',
        'baseline：24次均因未覆盖需求停止，未发现已排队任务丢失、取消或失效；一次scope提交拒绝（调用43）与队列维护无关。',
        'filter_projection：2550.910提交d132-w460、d132-w468，not_before均为2658，分别绑定机台925和927。w460于2686.681794实际按原任务ID派工；该时刻未触发模型。w468在2703评估边界仍未派工，此时机台927仍busy，不能判定为丢任务。',
        '实际维护记录（仿真时刻 | 替换任务 | not_before前值→后值）：',
    ]
    for c in witness['changes']:
        d = c['diff']['not_before']
        lines.append(f"{c['time']:.6f} | {c['id']} | {d['before']:.6f}→{d['after']:.6f}")
    lines += [
        '源码原因：plan_delta.py的past_start检查要求非冻结任务not_before>=当前时刻；已提交且尚未派工的旧任务一旦跨过not_before，后续提交必须显式替换。上述10项替换只变了not_before，属于可确认的维护负担。',
        '边界：6轮本来就在为别的需求重排，不能将10项替换计成10次额外模型调用。w460最后的not_before=2683.878530早于实际可派工2686.681794，没有证据表明此维护延误了它。',
        '另一个静态风险：environment._gaps只要机台存在pending或hold就不报缺口，而_run_planned_now仅尝试该机台队首。因此“有队列”不自动等于“有有效可执行覆盖”；扩大预排后可能出现队首未就绪遮住其他ready任务。基线本次没有pending，所以这不是本轮24次的已证实原因。',
        '环境已有跳步/访问变化失效检测，能阻止被skip的旧任务继续隐藏缺口；它请求模型重排，不会自行选择替代任务。',
        '', '与M0.5结论的关系及讨论范围',
        'M0.5 HE-Q02/03区分多任务承诺、物理就绪和模型重入；这次证据与该区分一致。现有propose_delta数组支持多机多任务，第11次也一次新增并派工4项，协议没有单任务硬上限。',
        '后续讨论应分别围绕：7次ready候选的事实呈现与预排范围；4次已知后继的条件承诺；13次抽样/跳步的分支语义；已承诺等待任务的时间维护。先区分这些原因，再决定具体改法。',
        '本次没有修改提示词、接口、调度或触发规则；没有启动模型、求解器、模拟器或新实验。',
        '本报告没有声称能确定减少11次或任何固定比例的重排，也没有作质量不退化、统计显著或长期产线效果的结论。',
        '', '可复核证据',
        str(OUT / 'attribution.json') + '：24行因果链、公共事实、请求可见性、原始事件和队列核查。',
        str(OUT / 'queue_witness.json') + '：filter_projection预排、10次替换、实际派工与源文件哈希。',
        str(OUT / 'source_objects.json') + '：baseline已读取内容对象的SHA-256和字节长度。',
        str(OUT / 'queue_source_objects.json') + '：filter_projection已读取内容对象的SHA-256和字节长度。',
        str(SOURCE / 'completion_verification.json') + '：原实验最终核验。',
        str(SOURCE / 'workspace/src/smt_fullfab/environment.py') + '：_run_planned_now、_gaps和advance_plan。',
        str(SOURCE / 'workspace/src/smt_fullfab/plan_delta.py') + '：past_start及保留任务编译规则。',
        str(SOURCE.parent.parent / 'research_harness_efficiency_20261016/m0.5_research/dossier.md') + '：HE-Q02/03与多任务/重排触发研究。',
        '',
        f"只读校验：baseline内容对象{data['verification']['content_objects_verified']}个、filter_projection内容对象{witness['summary']['content_objects_verified']}个，解压内容SHA-256全部匹配；被跟踪源文件分析前后哈希一致。SQLite使用mode=ro&immutable=1且WAL为空。",
        '最终审计已通过物理/来源与已报告成本核验，但原实验存在未知token用量；本分析没有改变该边界。',
    ]
    path = OUT / '24次重排逐次归因.txt'
    path.write_text('\n'.join(lines) + '\n')
    return path


if __name__ == '__main__':
    data = json.loads((OUT / 'attribution.json').read_text())
    assert data['summary']['stops'] == 24 and data['summary']['looked_up_followup_operations'] == 27
    assert Counter(r['category'] for r in data['rows']) == Counter(data['summary']['category_counts'])
    assert data['verification']['source_files_unchanged']
    witness = queue_witness()
    path = write_report(data, witness)
    print(json.dumps({'report': str(path), 'queue_summary': witness['summary']}, ensure_ascii=False, indent=2))
