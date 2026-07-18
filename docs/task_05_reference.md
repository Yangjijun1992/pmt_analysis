请完成 pmt_analysis 项目的任务 5：实现 SPE gain 分析模块。

背景：
1. 当前项目已经具备：
   - CLI 入口
   - run_id -> runinfo.json 自动发现
   - RunInfo 解析
   - RAW 数据读取
   - dark count 分析
2. 真实目录规则为：
   - /mnt/data/TPC/{runtype}/{run_id}/runinfo.json
   - /mnt/data/TPC/{runtype}/{run_id}/RAW/
3. gain 分析逻辑来源于：
   - example_code/pmt_gain_example.ipynb

请完成以下工作：

1. 必须先阅读：
   - example_code/pmt_gain_example.ipynb
2. 明确识别 notebook 中：
   - gain 分析使用的输入数据
   - pulse 或 sample 的提取方式
   - 是否做基线扣除
   - SPE 特征的定义（如 pulse height / charge 等）
   - histogram 的构建方式
   - 拟合函数与参数
   - gain 的最终定义
   - 绘图逻辑与 exploratory 逻辑
3. 只实现 SPE gain 分析，不要实现 APP、数据库写入。
4. 新增文件：
   - src/pmt_analysis/analysis/gain.py
5. 如项目中已有 src/pmt_analysis/analysis/types.py，请在其中增加 gain 相关 dataclass；否则可新增该文件，或放到 models.py，但要保持结构清晰。
6. 建议实现以下对象：
   - GainSample
   - GainFitResult
   - GainAnalysisResult
7. 建议在 gain.py 中实现以下接口：
   - extract_gain_samples(bundle)
   - build_spe_histogram(samples, bins=None)
   - fit_spe_spectrum(hist_counts, hist_edges)
   - compute_gain_value(fit_result)
   - analyze_gain(bundle)
8. 必须优先复用 notebook 中已有的分析口径，不要自行发明另一套 gain 定义。
9. 如果 notebook 中对 gain 的计算公式、拟合模型、参数初始化有明确实现，必须尽量忠实保留。
10. 如果 notebook 依赖 scipy、ROOT、uproot 等第三方库，必须明确列出依赖，并在缺依赖时给出清晰错误。
11. 修改 pipeline.py：
   - 在 dark count 分析之后调用 gain 分析
   - 打印 gain 摘要：
     - sample_count
     - feature_name
     - fit_success
     - gain_value
     - fit_parameters
12. 更新 README.md，补充当前 SPE gain 分析能力与依赖说明。
13. 使用 Python 3.9+ 兼容语法。
14. 保持模块职责清晰，不要做无关重构。

请按以下格式输出：
1. notebook 中 gain 分析逻辑摘要
2. 修改文件列表
3. gain 模块设计说明
4. 完整代码
5. 依赖说明
6. 运行方式
7. 输出字段说明
8. 风险与假设

验收标准：
对于一个可访问的 run_id，程序能够在 dark count 分析之后继续执行 SPE gain 分析，并输出结构化的 gain 结果摘要，而不是停留在数据读取或 dark count 阶段。
