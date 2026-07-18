请完成 pmt_analysis 项目的任务 4：实现 dark count 分析模块。

背景：
1. 当前项目已经具备：
   - CLI 入口
   - run_id -> runinfo.json 自动发现
   - RunInfo 数据结构
   - runinfo 解析
   - RAW 数据读取
2. 真实目录规则为：
   - /mnt/data/TPC/{runtype}/{run_id}/runinfo.json
   - /mnt/data/TPC/{runtype}/{run_id}/RAW/
3. 原始数据读取逻辑来自：
   - example_code/pmt_dark_cout_rate_example.ipynb

dark count 的规则必须按以下定义实现：
1. dark count rate = total_dark_count / total_daq_run_time_length
2. asymmetry = pulse_height / pulse_range
3. asymmetry > 0.7 判为 dark count
4. asymmetry <= 0.7 判为 noise

请完成以下工作：

1. 必须先阅读：
   - example_code/pmt_dark_cout_rate_example.ipynb
2. 明确识别 notebook 中：
   - pulse 提取逻辑
   - pulse_height 定义
   - pulse_range 定义
   - DAQ 总时长计算方式
   - dark count 核心分析逻辑
   - 绘图/探索逻辑
3. 只实现 dark count 分析，不要实现 SPE gain、APP、数据库写入。
4. 新增文件：
   - src/pmt_analysis/analysis/dark_count.py
5. 建议新增：
   - src/pmt_analysis/analysis/types.py
   如果你认为更合适，也可以把分析结果 dataclass 放到 models.py
6. 定义结构化结果对象，至少包含：
   - PulseRecord
   - DarkCountResult
7. 建议在 dark_count.py 中实现：
   - extract_pulses(bundle)
   - compute_pulse_record(pulse, asymmetry_threshold=0.7)
   - estimate_total_daq_run_time_length(bundle)
   - analyze_dark_count(bundle, asymmetry_threshold=0.7)
8. 必须忠实保留以下规则到代码中：
   - asymmetry = pulse_height / pulse_range
   - asymmetry > 0.7 -> dark_count
   - asymmetry <= 0.7 -> noise
9. 必须处理 pulse_range == 0 的边界情况，不能直接除零崩溃。
10. 更新 pipeline.py：
   - 在 RAW 数据读取之后调用 dark count 分析
   - 打印摘要：
     - asymmetry_threshold
     - total_pulse_count
     - total_dark_count
     - total_noise_count
     - total_daq_run_time_length
     - dark_count_rate
11. 如果 notebook 中已经有稳定的 DAQ 总时长计算方法，必须复用；如果确实无法稳定获得，必须清楚说明，并让 dark_count_rate 返回 None，而不是伪造数值。
12. 更新 README.md，补充 dark count 定义与当前功能边界。
13. 使用 Python 3.9+ 兼容语法。
14. 保持模块职责清晰，不要做无关重构。

请按以下格式输出：
1. notebook 中 dark count 分析逻辑摘要
2. 修改文件列表
3. dark count 模块设计说明
4. 完整代码
5. 运行方式
6. 输出字段说明
7. 当前未实现内容
8. 风险与假设

验收标准：
对于一个可访问的 run_id，程序能够在 RAW 数据读取之后继续执行 dark count 分析，并输出 dark count rate 与分类统计摘要，而不是停留在数据读取阶段。
