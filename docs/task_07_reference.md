请完成 pmt_analysis 项目的任务 7：实现分析结果数据库写入。

要求如下：

1. 读取 runinfo.json 中的 mapping 信息，建立 board/channel_id 与 pmt_id 的对应关系。
2. 当前分析结果仍包含 channel_id；在写入数据库前，必须通过 mapping 将其替换/映射为 pmt_id。
3. 数据库存储应以 pmt_id 为主识别对象，channel_id 和 board_id 仅作为辅助追踪字段保留。
4. 需要写入数据库的字段包括：
   - dark_rate
   - spe_gain
   - after_pulse_probability
5. 数据库写入逻辑参考：
   - example_code/pmt_db_write.py
   但不要直接照搬脚本，必须重构为项目内可复用模块。
6. 建议新增模块：
   - src/pmt_analysis/db/mapping.py
   - src/pmt_analysis/db/models.py
   - src/pmt_analysis/db/writer.py
7. 修改 pipeline.py，在 dark count、gain、APP 分析完成后：
   - 读取 mapping
   - 构建按 pmt_id 聚合的分析结果记录
   - 写入数据库
8. 必须处理以下异常：
   - mapping 缺失或重复
   - 通道无法解析为 pmt_id
   - 数据库连接失败
   - 数据库写入失败
9. 更新 README，说明：
   - 数据库写入已支持
   - board/channel_id 会先映射为 pmt_id
   - 写入字段为 dark_rate、spe_gain、after_pulse_probability
10. 不要无关重构分析算法；本任务重点是 mapping 解析、结果重组、数据库持久化。

验收标准：
给定一个可访问的 run_id，程序能够基于 runinfo.json 的 mapping 将分析结果中的 channel_id 映射为 pmt_id，并把 dark_rate、spe_gain、after_pulse_probability 正确写入数据库。
