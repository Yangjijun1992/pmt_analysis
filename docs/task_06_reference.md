请完成 pmt_analysis 项目的任务 6：实现 APP（Afterpulse Probability）分析模块。

背景：
1. 当前项目已经具备：
   - CLI 入口
   - run_id -> runinfo.json 自动发现
   - RunInfo 解析
   - RAW 数据读取
   - dark count 分析
   - SPE gain 分析
2. 真实目录规则为：
   - /mnt/data/TPC/{runtype}/{run_id}/runinfo.json
   - /mnt/data/TPC/{runtype}/{run_id}/RAW/
3. APP 分析逻辑来源于 example_code 中与 afterpulse / APP 对应的 notebook 或脚本

请完成以下工作：

1. 必须先阅读 example_code 中与 APP 对应的 notebook 或脚本。
2. 明确识别 notebook 中：
   - APP 分析使用的输入数据
   - 主脉冲定义
   - afterpulse 定义
   - 主脉冲搜索窗口
   - afterpulse 搜索窗口
   - 幅度/电荷/时间阈值
   - APP 的最终定义
   - 绘图逻辑与 exploratory 逻辑
3. 只实现 APP 分析，不要实现数据库写入。
4. 新增文件：
   - src/pmt_analysis/analysis/app.py
5. 如项目中已有 src/pmt_analysis/analysis/types.py，请在其中增加 APP 相关 dataclass；否则可新增该文件，或放到 models.py，但要保持结构清晰。
6. 建议实现以下对象：
   - AfterpulseRecord
   - AppAnalysisResult
7. 建议在 app.py 中实现以下接口：
   - extract_main_pulses(bundle)
   - find_afterpulse_candidates(bundle, main_pulses)
   - classify_afterpulse(candidate)
   - compute_app_value(main_pulse_count, main_pulse_with_afterpulse_count)
   - analyze_app(bundle)
8. 必须优先复用 notebook 中已有的分析口径，不要自行发明另一套 APP 定义。
9. 必须从 notebook 中确认 APP 的分子与分母定义；如果 notebook 中已有明确公式，必须忠实保留。
10. 如果 notebook 依赖 scipy、ROOT、uproot 等第三方库，必须明确列出依赖，并在缺依赖时给出清晰错误。
11. 修改 pipeline.py：
   - 在 dark count 和 gain 分析之后调用 APP 分析
   - 打印 APP 摘要：
     - main_pulse_count
     - afterpulse_candidate_count
     - main_pulse_with_afterpulse_count
     - app_value
     - main_pulse_window
     - afterpulse_window
12. 更新 README.md，补充当前 APP 分析能力与依赖说明。
13. 使用 Python 3.9+ 兼容语法。
14. 保持模块职责清晰，不要做无关重构。

请按以下格式输出：
1. notebook 中 APP 分析逻辑摘要
2. 修改文件列表
3. APP 模块设计说明
4. 完整代码
5. 依赖说明
6. 运行方式
7. 输出字段说明
8. 风险与假设

验收标准：
对于一个可访问的 run_id，程序能够在 gain 分析之后继续执行 APP 分析，并输出结构化的 APP 结果摘要，而不是停留在 dark count 或 gain 阶段。
