# 最终报告新增段落独立复核签署

审查日期：2026-10-09。审查者：独立静态基准与报告审查 Agent。

**结论：在本次指定范围内，未发现未解决的实质问题，可以将本记录作为最终 report integrity 签署的证据之一。** 本结论绑定以下报告版本；不自动适用于之后的修改。

- 报告：[docs/REPORT_zh.md](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/REPORT_zh.md)
- SHA256：`17ee9167ce6cfa6f187701723bda9aed056677cf695eaf11b5c8481dc4175bd5`
- 只读范围：最终恢复段、全轮资源与开发诊断段、SMT预约占用/日历停机及组范围、F跨phase配对，以及此前提出的mk05因果措辞。
- 操作：读取已保存JSON/CSV/文档及指标定义源码，少量求和、配对、区间汇总与哈希核对。新增评测模型、solver、仿真、回放均为0；没有运行测试套件、生成图片、修改报告本体或提交Git。

## 恢复结果与原始分母

原始核心134/135成功、辅助45/45成功；原始静态107/108成功，与唯一恢复后108/108逻辑格点交付已分别说明。补充结果未回填原始成功率、质量条件均值或原180条统计。恢复审计保留原`mk08_B_r1`为failed，唯一`mk08_B_r1__channel_recovery_1`为success、valid且audit_pass，makespan为523；不存在额外恢复目录。

恢复原始记录确认端到端248.2225706659956秒、1次模型请求、零solver；input 6132、output 9558、cached input 2560、reasoning output 8610。报告正确将缓存与reasoning视为子集，未重复求和，未把原失败未知usage或未知货币费用记零。

原失败端到端300.1152649159776秒，通道自身300.02364050003234秒。两次活动累计548.3378355819732秒；恢复等待10519.239591秒，日历跨度11067.632939秒，报告舍入全部正确。活动累计采用运行器计时，日历跨度采用时间戳，二者是分别保存的量；报告没有把等待混入活动预算。恢复资格与协议均明确为事后可靠性补充，没有写成首次100%成功。

## 正式资源与开发诊断

保存的预算审计`valid=true`、errors为空，1220行账本、602个唯一预约与602个finish，无pending。报告所列值与该审计及恢复原记录一致：

|范围|模型外层尝试|已知input+output|未知usage尝试|solver预留秒|活动端到端秒|
|---|---:|---:|---:|---:|---:|
|原180条|239|1892097|1|3149.9|11675.620526786777|
|恢复1条|1|15690|0|0|248.2225706659956|
|正式合计181条|240|1907787|1|3149.9|11923.843097452773|

正式input 1718787与output 189000之和正确；cached input 259584、reasoning output 153454未再次累加。实际solver墙钟2010.0861125399824秒、模型通道9469.543040498625秒、全部181条货币费用null均与审计相符。报告区分预留预算、实际耗时、活动时间与日历时间；已知token准入阈值未冒称全部计费用量已知，也保留内部HTTP重试和协作/研究/审计模型计费不可得的范围限制。

开发账本23次模型尝试、已知183947 token、2次usage未知、solver预留446.2秒均正确。两个保存的开发结果表包含19条静态和3条SMT实验，合计21成功、1失败；端到端合计1249.3371059151832秒，符合1249.34秒。另两次通道探测的账本finish分别为失败、成功，未混入这22条实验。旧`dev_mk10_B`失败和后续紧凑动作开发记录均保留，报告没有写成删除失败后首次成功。

11条早期开发缺token_admission和72条静态A/F缺solver_calls均明确作为保留缺口及重建核对，不冒充原记录本来包含这些字段。本复核读取已保存的独立预算审计，没有重新逐条执行预算审计；账本以外的早期非模型SMT测试/诊断CPU不据此宣称已全部计入正式活动耗时。

## SMT预约占用、停机与组范围

对设备CSV作直接汇总，得到27条核心运行、每条913个互异生产设备，共24651行；受控设备仅9与790，共54行，其预约占用比例全部1.0，日历停机比例全部0.0。组表为27×11＝297行，11个组的设备数之和为913。报告没有将400个Delay虚拟资源计入生产机分母。

独立从组观察表重算各组最小/最大值，与`smt_group_ranges.csv`全部一致。报告引用区间正确：Diffusion预约占用96.60%–97.02%、日历停机0.81%–2.46%；Litho预约占用86.72%–87.65%；Dry_Etch为79.07%–79.46%。Diffusion确为所列全厂组均值中预约占用最高者。范围来自27条原核心运行，不是置信区间。

指标定义采用dispatch至machine_ready预约区间的并集，并按实际停机事件延长未结束的预约；日历停机另取序列化区间并集。预约含setup、load/unload、cadence及片数PM等，不等于纯加工利用率；它与日历停机可以重叠。报告已明确不能直接相加、不能由100%占用断言全厂瓶颈，并将容量压力描述限定为短窗口观察及待干预验证，未发现过度断言。

## F配对与C解释

F对A表有9个互异scenario/repeat键，两侧阶段分别为`acceptance_smt_v1`与`auxiliary_smt_v1`，均有认证标记。逐行重算`100 × (F_queue_area / A_queue_area − 1)`与表中数值完全一致；三个场景分别为+0.2847998455%、+0.0150283100%、−0.3779215695%，等权均值−0.0260311380%。来源清单的四项输入SHA256均与当前文件一致。此前“辅助CSV原列为空，必须保留跨阶段来源”的P3问题已关闭。

mk05解释已改为首候选得到173、第二次候选175未采用，因此未显示反馈迭代额外收益；同时明确不能分离初始参数因素或确认跨实例自适应贡献，需在预留集匹配固定首配置。此前因果措辞P2问题已关闭。报告没有将预定F、同外生种子重复或3个独立场景扩张为普遍Agent优势证据。

## 证据绑定与签署边界

|证据|SHA256|
|---|---|
|[预算审计](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/artifacts/final/qa/budget_audit.json)|`72c27e779dedd95f457424d2b3b44f49e3876b6f187137d59f69a0e283ab249a`|
|[恢复审计](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/artifacts/static_recovery/audit.json)|`93e4b1f5150468414798ab484b230806222a76927a456c5785e443d575f2723c`|
|[F配对表](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/artifacts/final/smt_fixed_pairing.csv)|`f5a213d080fc9805936117078b6e36b5d83d7cdc53e96166315dbdb1a27598e0`|
|[配对及组范围来源](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/artifacts/final/smt_fixed_pairing_sources.json)|`5285a85773736fc0d43dd09fc9216d69e6cefe42c860874f6bcc955900ec03d1`|
|[组范围汇总](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/artifacts/final/smt_group_ranges.csv)|`7846f5efc15e77e9b1a9ce3fd93d55e47a11f10aa2ef9deba3c29e947fad235c`|
|[设备观察表](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/artifacts/acceptance_smt_v1/smt_machine_observation.csv)|`9b1fa91c34f4cb224115edb53b80acf3ddffda5c6c79d513c9301f99b74b7346`|

本签署接续[原180条报告数据复核](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/review-report-final-data.md)。最终整体验收、证据索引及八项核验签署由主Agent依保存证据另行生成；本次没有要求这些链接当前已存在，没有替代图像QA、Git/历史保护、README复现或整体验收门槛。报告文字和图片的主Agent视觉核验由其单独签署，本记录不冒称本次逐图检查。
