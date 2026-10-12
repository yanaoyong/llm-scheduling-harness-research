# 首轮统一问题规范：PADL-2023，flex=1

本规范锁定 `prosysscience/FJSP-SMT2020` 的提交
`6253f982df13886ab75d9bc639bfaff045b2829a`，使用该提交的
`PADL-2023/encoding_msw.lp`、`parsing.lp`、`machine_selection.lp` 和对应实例。
这不是整个仓库中所有论文版本的统一模型，也不是完整半导体晶圆厂仿真。
三种方案共享以下语义和同一个独立校验器。

## 数据与身份

- `wip(L,P,Cur_s,Prio,W,R,D)` 表示当前在制品。需要安排产品 `P` 的全部
  `S >= Cur_s` 工序；身份是完整四元组 `(L,P,S,Prio)`，JSON 写为
  `L:P:S:Prio`。不能只使用 `L`，因为公开实例中同一个 `L` 有不同产品。
- `product(P,S,A,G,Pro_t,Pro_unit,Cas_interval,Setup_t,Setup_n)` 指定工序组、
  加工时间及所需 setup。工序时长直接使用 `Pro_t`，即使 `Pro_unit=wafer`
  也不乘以晶圆数 `W`。
- 在该编码中，`Pro_unit`、级联标记/间隔、工具装卸时间、产品行的
  `Setup_t`、交期 `D` 不产生额外硬约束。setup 时间来自 `setup_change`。
  这些原始字段保留在来源文件中，但不擅自加入本次问题。
- `machine_selection.lp` 对每个工具组使用
  `min(原始设备编号去重数,该组剩余工序数)` 台设备，并生成从 `1` 开始的连续
  编号。`flex=1` 允许在该组这些设备中选择任意一台；不跨工具组分配。
- 原编码按 `L` 投影 release 和 wafer。锁定公开语料中没有同一 `L` 的
  冲突值；解析器拒绝冲突输入以免默默选择一种解释。

## 硬约束

1. 每个需要安排的工序恰好出现一次；设备编号必须属于工序工具组。
   工序不可拆分、不可中断；start/end 为非负整数，`end=start+Pro_t`。
2. 同一 `(L,P,Prio)` 的相邻步骤按 `S,S+1` 前后衔接，后序 start 不小于
   前序 end。当前首步不得早于 release；如果该首步产生 setup，时间下界为
   `release + setup_duration`。
3. 一台设备上的加工区间互不重叠。每次非初始维护和换型发生在目标工序之前。
   若同机上一工序是 `u`，本工序是 `v`，则
   `start(v) >= end(u) + sum(本次维护时长) + 本次setup时长`。
   设备间独立；本轮没有组批、批容量或批同步决策。
4. `pm(E,G,counter_based,Max,Dur,Min)` 以经过的晶圆数累计负载；每个工序
   增加其 lot 的 `W`，不是增加 1。
   `time_based` 以经过的加工时长累计，排队、空闲、setup、维护时间都不计入。
5. 每种维护事件独立划分段。段从一次维护所关联的工序开始，包含该工序，
   到下一次同类维护前结束。所有段负载都不得大于 `Max`；有下一次同类维护
   的段还必须不小于 `Min`。最后一个段免除 `Min`，仍需满足 `Max`。
6. 每台实际使用设备的第一个工序必须显式分配该工具组的全部维护事件。
   **按照源代码，这些初次维护不增加任何时间。** 设备以后同时分配多个维护
   事件时，它们的正时长相加，不取最大值；维护与 setup 的时间也相加。
7. 非零 `Setup_n` 表示所需 setup；`Setup_n=0` 表示继承同机此前最近的
   非零 setup，机器从未具有非零 setup 时才保持 0。不是每次 0 都切换回 0。
   设备首工序建立初始 setup；此后有效 setup 改变且新值非零时发生换型。

## 初次 setup 的源代码边界行为

为了复现所选公开模型，本轮保留以下不宜直接解读为真实工厂规则的行为：

- 机器首工序若后面还有同机工序，额外要求 `start >= initial_setup_duration`。
- 机器首工序若又是该 lot 的当前首步，要求 `start >= release + setup_duration`。
- 若机器只有这一道工序，且它不是该 lot 的当前首步，原编码没有独立的
  initial setup 下界；仍需满足该 lot 的前序加工结束约束。
- setup 不在 lot 前序 end 之后再必然加一次：存在设备上的时间下界、lot
  前序结束下界以及上述 release 下界，取其最大值。因此允许预先做 setup。

校验器和 B 的时间计算器均保留这些规则。原 ASP 交叉测试包含“前序于 1
结束、下一台机器唯一工序 setup=10 却可在 1 开始”的专门例子；这是
对版本语义的忠实保留，不是为了本次实验削弱约束。

## 统一目标及辅助指标

主目标是 makespan，即所有加工工序完成时间的最大值。原编码在各 lot
末步上约束 makespan；在完整连续工艺路线且满足前后序约束的排程中，这与
全部工序最大 end 等价。所有方案评分从提交的实际 start/end 重新计算，
不信任求解器报告的 success、model objective 或 Agent 自报分数。

`setup_change(G,S,SetupDuration,Min_runs)` 的 `Min_runs` 是软要求。
一个 setup 从建立到下一个 setup 改变之间包含的工序数不足 `Min_runs`
时，增加 1 个 `setup_violations`，无论差额多少。设备最后一个 setup
段不罚分。setup=0 继承后的工序也计入当前段。

原 ASP 保留 setup 弱约束，但本次原生 C++ makespan 优化器每次接受模型后
进入严格更小的 makespan 边界，并没有完整执行“固定最优 makespan 再穷尽
优化 setup”的第二阶段。因此本轮报告以 makespan 为共同主指标，setup
违规作为辅助诊断，**不声称证明了严格字典序最优**。

## 公共输入输出

`src.problem.load_instance(path)` 使用 Python 标准库解析 ground facts。
返回主要字段：

```json
{
  "operations": [{"id":"1:3:16:10","lot":1,"product":3,"step":16,
    "priority":10,"group":"lithotrack_fe_95","duration":13,
    "setup":"su494_3","wafers":25,"release":0,"is_first":true,
    "predecessor":null}],
  "machines": {"lithotrack_fe_95":[1]},
  "maintenance": [{"name":"event_name","group":"lithotrack_fe_95",
    "type":"time_based","min":15,"max":50,"duration":23}],
  "setups": {"lithotrack_fe_95":{"su494_3":{"duration":14,"min_runs":2}}}
}
```

上面只是字段说明，完整内容必须来自已锁定实例，不能把该片段当成测试数据。
统一排程是：

```json
{"operations":[{"id":"1:3:16:10","machine":1,"start":14,"end":27,
  "maintenance":["lithotrack_fe_95_wk","lithotrack_fe_95_mn"]}]}
```

维护列表表示在该工序之前分配了哪些事件。独立校验器从实例及记录自行
重建设备顺序、setup 和维护段，不信任可选的 `effective_setup`、
`setup_duration`、`maintenance_duration`、`objective` 元数据。

`src.validator.validate_schedule(instance,schedule)` 返回 `feasible`、逐项
`violations`、重算 `objective`、每机顺序和维护段诊断。不可行记录中的
objective 仅为诊断值，不能计入成功质量比较。

## B 的动作与工具边界

大模型必须完整提供拓扑派工顺序，以及每步设备和维护事件：

```json
{"actions":[{"id":"1:3:16:10","machine":1,
 "maintenance":["lithotrack_fe_95_wk","lithotrack_fe_95_mn"]}]}
```

`src.dispatch.build_schedule(instance,actions)` 只追加模型指定工序并传播
时间下界，不排序、不选设备、不插入维护、不搜索、无求解器依赖、无参考答案。
它会拒绝未就绪、重复、非法设备、初次维护漏配、维护过早、负载超限和不完整
动作，并提供结构化反馈；调用者可将反馈交给同一模型修订当前实例。
动作数组给出的机器顺序和维护选择不会被工具自动修复。

## 校验证据

- `tests/test_problem_validator.py` 的 18 项测试使用手工排程和人为违规；
  冒烟实例独立手算为 `[2,5]、[5,7]、[15,19]`，makespan=19、setup违规=1。
- `tests/test_source_equivalence.py` 对三种合法 lot 拓扑排列与全部 64 种
  维护指派组合构造 192 个固定排程。额外 ASP 约束锁定机器、维护、start；
  直接调用未修改原编码，比较 SAT/UNSAT 及 setup 弱约束代价。
- 另交叉检查 5 个时间边界/空闲例子、singleton setup 例子，以及已有开发
  instance01 的每一个原生 solver witness。未为这些测试求解正式验收实例。
- 交叉记录在 `runs/development/validator_equivalence/`。每例保存固定 ASP、
  原 solver stdout/stderr、命令、候选排程及对比结果。该依赖只用于验证测试；
  生产独立校验器本身完全不调用原模型或任何求解器。

本规范仅覆盖锁定 PADL 语料和测试的连续路线、正整数加工时间、每个活跃
工具组均有维护事件的数据范围。对没有 PM 的自定义工具组，原编码构造
`pair` 的行为不同，本轮解析器明确拒绝，不声称支持尚未验证的扩展场景。
