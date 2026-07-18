请完成 pmt_analysis 项目的任务 6：重构并实现 APP（After Pulse / Afterpulse Probability）分析模块。

严格要求：
本任务必须基于 `example_code/pmt_after_pulse_example.py` 提炼 after pulse 核心算法，但不得复用该 example 的原始数据读取方式。当前项目必须继续遵循统一数据流：

- `run_id -> runinfo.json` 自动发现
- `RunInfo`
- `RawDataReader.read(runinfo) -> RawDataBundle`
- 各分析模块统一接收 `RawDataBundle`

你的目标是：
分析 `example_code/pmt_after_pulse_example.py` 的主要算法，将其中与数据源耦合的实现拆开，重写为适配当前项目统一输入的数据分析模块。

请完成以下工作。

1. 先阅读并分析：
- `example_code/pmt_after_pulse_example.py`

2. 必须明确区分并总结该文件中的以下部分：
- 数据读取逻辑
- 波形预处理逻辑
- 主脉冲识别逻辑
- after pulse 寻峰逻辑
- 候选筛选逻辑
- APP 统计逻辑
- 绘图/调试逻辑

3. 必须明确指出：
- 哪些代码属于旧的数据读取耦合，应该丢弃
- 哪些算法思想应该保留
- 哪些部分必须改写为适配 `RawDataBundle`

4. 只复用 example 中的核心算法思想，不要复用其原始读取方式、脚本结构或专用输入格式。

5. 新增文件：
- `src/pmt_analysis/analysis/app.py`

6. 如项目中已有：
- `src/pmt_analysis/analysis/types.py`
请在其中增加 APP 相关 dataclass；
如果没有，也可以新增该文件，或放到 `models.py`，但要保持结构清晰。

7. 建议新增以下数据结构：

- `MainPulseRecord`
  - `event_index: Optional[int]`
  - `channel_index: Optional[int]`
  - `sample_index: Optional[int]`
  - `time: Optional[float]`
  - `height: Optional[float]`
  - `charge: Optional[float]`
  - `metadata: Dict[str, object]`

- `AfterpulseRecord`
  - `event_index: Optional[int]`
  - `channel_index: Optional[int]`
  - `main_pulse_time: Optional[float]`
  - `afterpulse_time: Optional[float]`
  - `delay_time: Optional[float]`
  - `height: Optional[float]`
  - `charge: Optional[float]`
  - `passes_selection: bool`
  - `metadata: Dict[str, object]`

- `AppAnalysisResult`
  - `bundle: RawDataBundle`
  - `main_pulses: List[MainPulseRecord]`
  - `afterpulses: List[AfterpulseRecord]`
  - `main_pulse_count: int`
  - `afterpulse_candidate_count: int`
  - `main_pulse_with_afterpulse_count: int`
  - `app_value: Optional[float]`
  - `main_pulse_window: Optional[tuple]`
  - `afterpulse_window: Optional[tuple]`
  - `metadata: Dict[str, object]`

8. 建议在 `src/pmt_analysis/analysis/app.py` 中实现以下接口：
- `iter_waveforms(bundle)`
- `preprocess_waveform(waveform)`
- `find_main_pulse(processed_waveform)`
- `find_afterpulse_candidates(processed_waveform, main_pulse)`
- `select_afterpulses(candidates)`
- `compute_app_value(main_pulse_count, main_pulse_with_afterpulse_count)`
- `analyze_app(bundle)`

9. 各接口职责要求：

- `iter_waveforms(bundle)`
  - 从 `RawDataBundle` 中统一枚举事件/通道/波形
  - 解决 reader 输出结构与 APP 算法之间的适配问题

- `preprocess_waveform(waveform)`
  - 复用 example 中的基线处理、极性处理或必要预处理思想
  - 不要引入与 example 完全不同的新物理口径

- `find_main_pulse(processed_waveform)`
  - 复用 example 中主脉冲识别逻辑
  - 返回结构化主脉冲对象

- `find_afterpulse_candidates(processed_waveform, main_pulse)`
  - 复用 example 中主脉冲后时间窗内的寻峰算法
  - 返回结构化候选 after pulse 列表

- `select_afterpulses(candidates)`
  - 应用 example 中的有效候选筛选规则
  - 保留通过筛选的 after pulse

- `compute_app_value(main_pulse_count, main_pulse_with_afterpulse_count)`
  - 必须严格按 example 中 APP 定义实现
  - 不要自行发明新的 APP 公式

- `analyze_app(bundle)`
  - 串联整个 APP 分析流程
  - 返回结构化 `AppAnalysisResult`

10. 关于“重构出新的算法实现”的要求：
- 不是让你发明新的物理定义
- 而是要把 example 中耦合在旧读取方式里的算法拆出来
- 重写成一套：
  - 与数据源解耦
  - 输入统一
  - 模块清晰
  - 可测试
  - 可被当前 pipeline 直接调用
- 即：
  - 保留原算法思想
  - 重写工程实现

11. 必须从 `example_code/pmt_after_pulse_example.py` 中识别并总结：
- 是否做基线估计/基线扣除
- 主脉冲如何定义
- after pulse 如何定义
- after pulse 搜索窗口如何定义
- 寻峰算法是什么
- 候选峰如何筛选
- APP 的分子和分母分别是什么
- APP 是否有明确公式
- 哪些部分只是绘图或 exploratory 调参，不能直接搬入正式代码

12. 关于 APP 定义的强制要求：
- 必须从 example 中确认：
  - APP 的分子是什么
  - APP 的分母是什么
- 必须明确是：
  - `afterpulse 总数 / 主脉冲总数`
  - 还是 `含 afterpulse 的主脉冲数 / 主脉冲总数`
  - 还是其他定义
- 如果 example 中已有明确公式，必须忠实保留
- 如果 example 中没有完全写清楚，必须在输出中明确说明假设，不能私自脑补并隐藏

13. 明确禁止的做法：
- 不要复用 `example_code/pmt_after_pulse_example.py` 的原始读取入口
- 不要要求用户传入 example 专用文件格式
- 不要让 `pipeline.py` 或 `app.py` 直接依赖 example 里的读取对象
- 不要把整份 example 脚本原样复制到正式代码中
- 不要无关重构 CLI、reader 或 dark count / gain 模块
- 不要改写 dark count / gain 的既有物理定义

14. 推荐异常设计：
在 `src/pmt_analysis/analysis/app.py` 中定义：
- `AppAnalysisError`
- `WaveformAdaptationError`
- `MainPulseExtractionError`
- `AfterpulseSearchError`

错误信息至少应包含：
- `run_id`
- 失败阶段
- 原始异常原因

15. 第三方依赖要求：
- 如果 example 中使用了第三方库，必须明确列出，例如：
  - `numpy`
  - `scipy`
  - `matplotlib`
  - `uproot`
  - `ROOT`
  - 其他自定义库
- 缺依赖时必须给出清晰错误
- 不允许静默失败

16. 修改 `src/pmt_analysis/pipeline.py`：
- 在 dark count 和 gain 分析之后调用 APP 分析
- APP 分析的输入必须是：
  - `analyze_app(bundle)`
- 打印 APP 摘要，至少包括：
  - `main_pulse_count`
  - `afterpulse_candidate_count`
  - `main_pulse_with_afterpulse_count`
  - `app_value`
  - `main_pulse_window`
  - `afterpulse_window`
- 如 example 中存在关键阈值，也建议打印，例如：
  - `amplitude_threshold`
  - `charge_threshold`
  - `delay_range`

17. 更新 `README.md`：
- 增加当前 APP 分析能力说明
- 明确写清：
  - APP 核心算法来源于 `example_code/pmt_after_pulse_example.py`
  - 但其数据读取方式没有沿用
  - 当前项目已统一为通过 `RawDataBundle` 作为分析输入
- 同时说明当前未实现：
  - 数据库写入
  - 批量持久化
  - 完整报告绘图系统

18. 使用 Python 3.9+ 兼容语法。

19. 保持模块职责清晰，不要做无关重构。

请按以下格式输出：
1. `example_code/pmt_after_pulse_example.py` 中 after pulse 核心算法摘要
2. 旧读取方式与新输入方式的差异说明
3. 新的 APP 算法分层设计
4. 修改文件列表
5. 完整代码
6. 依赖说明
7. 运行方式
8. 输出字段说明
9. 风险与假设

验收标准：
对于一个可访问的 `run_id`，程序能够继续使用当前项目统一的：
- `runinfo -> RawDataReader -> RawDataBundle`
数据流，在 RAW 数据读取之后执行 APP 分析，并输出结构化 APP 摘要，而不是回退到 example 脚本原来的读取方式。
