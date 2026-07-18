请完成 pmt_analysis 项目的任务 3：从 dark count notebook 中抽取原始数据读取逻辑。

背景：
1. 当前项目已经具备：
   - CLI 骨架
   - run_id -> runinfo.json 自动发现
   - RunInfo 数据结构
2. 真实目录规则为：
   - /mnt/data/TPC/{runtype}/{run_id}/runinfo.json
   - /mnt/data/TPC/{runtype}/{run_id}/RAW/
3. runinfo.json 中可能包含：
   - OUTFILE_PATH
   - OUTFILENAME
4. 原始数据定位应优先基于 RunInfo 进行，不再手工传 runinfo 文件路径

本任务目标：
阅读 example_code/pmt_dark_cout_rate_example.ipynb，识别其中与原始数据读取相关的逻辑，将其抽取为结构化 Python 模块，并接入 pipeline。当前只做数据读取，不实现 dark count 分析。

具体要求：
1. 必须先阅读：
   - example_code/pmt_dark_cout_rate_example.ipynb
2. 明确区分：
   - 数据读取逻辑
   - dark count 分析逻辑
   - 绘图或 exploratory 逻辑
3. 只抽取数据读取逻辑，不要实现 dark count 计算。
4. 新增文件：
   - src/pmt_analysis/io/raw_reader.py
5. 建议新增：
   - src/pmt_analysis/io/types.py
   如果你认为更合适，也可以把读取结果数据结构放到 models.py
6. 定义统一读取结果对象，例如 RawDataBundle，至少包含：
   - runinfo
   - source_path
   - data
   - data_format
   - event_count
   - channel_count
   - waveform_count
   - metadata
7. 在 raw_reader.py 中建议实现：
   - resolve_raw_input_path(runinfo)
   - load_raw_data_from_notebook_logic(input_path)
   - summarize_raw_data(data)
   - NotebookBasedRawDataReader.read(runinfo)
8. 必须优先复用 notebook 中已有的读取方式，不要凭空另造一套完全不同的读取逻辑。
9. 如果 notebook 依赖特殊第三方库，必须：
   - 明确列出依赖
   - 在代码中清晰导入
   - 缺依赖时给出明确错误
10. 不要把整本 notebook 原样复制进 .py 文件，必须整理成函数或类。
11. 修改 pipeline.py：
   - 在 get_runinfo 之后调用 reader
   - 打印原始数据基础摘要，例如：
     - source_path
     - data_type
     - data_format
     - event_count
     - channel_count
     - waveform_count
     - shape 或其他稳定统计
   - 最后明确提示 dark count analysis is not implemented yet
12. 更新 README.md，补充当前已支持 RAW 数据读取与其依赖说明。
13. 使用 Python 3.9+ 兼容语法
14. 使用 pathlib
15. 不要实现 dark count、SPE gain、验证图、APP、数据库写入

请按以下格式输出：
1. notebook 数据读取逻辑摘要
2. 修改文件列表
3. reader 接口设计说明
4. 完整代码
5. 第三方依赖说明
6. 运行方式
7. 当前返回的数据结构说明
8. 尚未解决的问题与假设

验收标准：
对于一个可用 run_id，程序能够执行到数据读取步骤，并打印读取结果的基础信息，而不是只停留在参数解析或 runinfo 解析阶段。
