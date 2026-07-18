任务 1：初始化项目骨架与 CLI 入口
任务目标
为 pmt_analysis 创建标准 Python 包结构，建立最小可运行的命令行入口，为后续接入 runinfo、数据读取和分析模块做准备。

需要 Agent 阅读的内容
项目根目录现有文件与目录结构

docs/agent_development_brief.md

docs/implementation_plan.md

输入背景
项目名称：pmt_analysis
当前已存在目录：

example_code/pmt_dark_cout_rate_example.ipynb

example_code/pmt_gain_example.ipynb

example_code/runinfo.json

具体要求
请完成以下内容：

建立 src/ 布局的 Python 包结构

建立 pyproject.toml

建立 src/pmt_analysis/__init__.py

建立 src/pmt_analysis/cli.py

建立 src/pmt_analysis/pipeline.py

建立 src/pmt_analysis/config.py

建立空的子模块目录：

src/pmt_analysis/io/

src/pmt_analysis/analysis/

src/pmt_analysis/plotting/

src/pmt_analysis/db/

CLI 提供最小命令：

pmt-analysis analyze --run-id 12345

pmt-analysis analyze --run-id 12345 12346

当前 CLI 可以只打印：

收到的 run_id 列表

runinfo 文件路径

output 目录

为后续扩展保留参数：

--runinfo-file

--output-dir

约束
不要实现真实分析逻辑

不要读取 notebook 内容

不要写数据库

必须使用 Python 3.9+ 兼容语法

必须保证安装后 CLI 可调用

尽量保持结构清晰，不要把所有逻辑塞进一个文件

交付要求
请输出以下内容：

修改/新增文件列表

每个文件的作用说明

完整代码

安装方式

运行示例

当前未完成但已预留的接口说明

验收标准
我应该能够执行：

pip install -e .
pmt-analysis analyze --run-id 12345

并看到命令行成功解析参数和打印输入信息。

任务 2：实现 runinfo.json 解析层
任务目标
实现从 example_code/runinfo.json 读取指定 run_id 信息的能力，并抽象成统一的 RunInfo 数据对象。

需要 Agent 阅读的内容
example_code/runinfo.json

docs/agent_development_brief.md

docs/implementation_plan.md

已完成的项目骨架代码

具体要求
请完成以下内容：

新增 src/pmt_analysis/models.py

新增或完善 src/pmt_analysis/runinfo.py

定义 RunInfo 数据结构，建议使用 dataclass

实现如下能力：

加载 runinfo.json

根据 run_id 查找对应信息

将原始 JSON 条目转换为统一 RunInfo

需要兼容以下情况：

run_id 不存在时，给出清晰错误

runinfo.json 结构与预期不完全一致时，尽量保留原始 metadata

在 CLI 或 pipeline 里接入 runinfo 解析

当执行：
pmt-analysis analyze --run-id 12345 --runinfo-file example_code/runinfo.json
时，能够打印该 run 的核心信息

约束
不要实现真实数据读取

不要假设未来数据库结构

不要丢弃 runinfo.json 中暂时无法解释的字段，保存在 metadata 中

RunInfo 中字段命名尽量通用，例如：

run_id

data_type

file_path

metadata

source

交付要求
请输出以下内容：

修改/新增文件列表

runinfo.json 结构理解说明

RunInfo 设计说明

完整代码

命令行运行示例

异常处理说明

验收标准
输入一个存在的 run_id 时，能够正确打印对应 RunInfo。
输入不存在的 run_id 时，能够清晰报错。

任务 3：从 dark count notebook 中抽取“原始数据读取逻辑”
任务目标
阅读 example_code/pmt_dark_cout_rate_example.ipynb，识别其中与“原始数据访问/读取”相关的代码，并将其抽取、整理为可复用的 Python 模块接口。

需要 Agent 阅读的内容
example_code/pmt_dark_cout_rate_example.ipynb

已完成的 runinfo.py、models.py、CLI 骨架

具体要求
请完成以下内容：

阅读 notebook，区分：

数据读取逻辑

分析逻辑

绘图或临时 exploratory 代码

当前只抽取“数据读取逻辑”，不要实现完整 dark count 算法

新增或完善：

src/pmt_analysis/io/raw_reader.py

设计统一的 reader 接口，例如：

RawDataReader

NotebookBasedRawDataReader

至少实现以下能力：

根据 RunInfo 获取数据位置

调用 notebook 中已有的数据读取方式

返回可供后续 dark count 分析使用的数据对象

如果 notebook 中依赖特殊第三方库，请明确列出依赖，并在代码中进行清晰导入

如果 notebook 中读取逻辑无法直接模块化，请尽量重构为函数，但不要改变其核心行为

在 CLI 或 pipeline 中增加一个 debug 打印，显示读取后的基本信息，例如：

数据对象类型

事件数

通道数

波形数量

任意你能稳定提取的基本统计

约束
不要在本任务中实现 dark count rate 计算

不要省略对 notebook 读取逻辑的说明

不要直接复制 notebook 全部代码到一个 .py 文件里，必须整理成函数/类

如果读取逻辑强依赖环境，必须在交付中说明风险点

尽量保持接口通用，后续 SPE gain 也可能复用

交付要求
请输出以下内容：

notebook 中数据读取逻辑的摘要

修改/新增文件列表

reader 接口设计说明

完整代码

所需第三方依赖说明

运行方式

当前返回的数据结构说明

尚未解决的问题与假设

验收标准
对于一个可用的 run_id，程序能够执行到数据读取步骤，并打印读取结果的基础信息，而不是只停留在参数解析阶段。

任务 4：实现 dark count 分析模块
任务目标
基于 example_code/pmt_dark_cout_rate_example.ipynb 中现有逻辑，实现结构化的 dark count 分析模块。

需要 Agent 阅读的内容
example_code/pmt_dark_cout_rate_example.ipynb

已完成的 raw_reader.py

RunInfo 数据结构

pipeline 和 CLI

已知分析规则
请以 notebook 的逻辑为主，同时满足当前已知规则：

dark count rate = total_dark_count / total_daq_run_time_length

asymmetry = pulse_height / pulse_range

asymmetry > 0.7 判定为暗计数

asymmetry <= 0.7 判定为噪声信号

具体要求
请完成以下内容：

新增或完善：

src/pmt_analysis/analysis/dark_count.py

定义 DarkCountResult 数据结构

将 notebook 中 dark count 核心逻辑抽取为函数

至少输出以下内容：

run_id

pmt_id（若 notebook 中可区分）

total_dark_count

total_daq_time

dark_count_rate

noise_count

asymmetry_threshold

其他必要 metadata

打印关键中间量，方便人工检查

将分析结果接入 pipeline

命令行运行后可以看到 dark count 分析摘要

约束
必须优先遵循 notebook 逻辑

若 notebook 中某些变量命名混乱，可以整理命名，但不能改变核心判定规则

不要加入与 notebook 无关的复杂优化

如果 pmt_id 暂时无法精确获得，可在结果中注明当前假设

保持结果结构清晰，便于后续数据库写入

交付要求
请输出以下内容：

notebook 中 dark count 分析逻辑摘要

修改/新增文件列表

DarkCountResult 设计说明

完整代码

如何运行

终端打印示例说明

当前假设与局限性

验收标准
运行分析后，能够输出 dark count 的关键参数值，而不是只返回原始数据对象。

任务 5：为 dark count 增加验证图输出
任务目标
在 dark count 分析完成后，自动生成本地验证图，供用户检查结果合理性。

需要 Agent 阅读的内容
已完成的 analysis/dark_count.py

notebook 中与 dark count 相关的绘图部分（如果有）

pipeline.py

具体要求
请完成以下内容：

新增或完善：

src/pmt_analysis/plotting/validation.py

为 dark count 至少生成一种验证图，优先考虑：

asymmetry 分布图

dark pulse 筛选前后对比图

其他 notebook 中已有的合理验证图

将图片保存到 output_dir

图片文件名中包含：

run_id

dark_count

将生成的图片路径加入结果对象或 bundle 中

在终端打印图像保存位置

约束
不要因为绘图导致主流程崩溃；绘图失败应给出明确提示

不要画与当前任务无关的复杂图

必须以“验证分析结果”为目的，不是为了美观

交付要求
请输出以下内容：

修改/新增文件列表

增加了哪些验证图，为什么选它们

完整代码

运行方式

图像保存路径示例

绘图失败时的处理说明

验收标准
运行一次 dark count 分析后，本地能生成至少一张验证图，并且命令行会打印其保存路径。

任务 6：从 gain notebook 中抽取数据读取差异与分析前置逻辑
任务目标
阅读 example_code/pmt_gain_example.ipynb，判断其数据读取方式是否可复用现有 reader；若有差异，补齐通用读取接口或增加专用支持。

需要 Agent 阅读的内容
example_code/pmt_gain_example.ipynb

src/pmt_analysis/io/raw_reader.py

src/pmt_analysis/models.py

src/pmt_analysis/pipeline.py

具体要求
请完成以下内容：

阅读 gain notebook，识别：

数据访问方式

与 dark count notebook 在数据结构上的差异

分析前置步骤

判断当前 raw_reader.py 是否足够支持 gain 分析

如有必要，重构或扩展 reader 接口，使其可同时服务：

dark count

SPE gain

在不破坏已有 dark count 流程的前提下，完善数据读取抽象

打印适合用于 gain 分析的基础信息，例如：

积分输入数组规模

波形数量

适合拟合的数据样本数

约束
本任务先聚焦“读取与前置准备”，不要求完成最终 gain 拟合

不要破坏已完成的 dark count 功能

如果 dark count 和 gain 最终需要不同 reader，可以合理拆分类，但要保持统一接口风格

交付要求
请输出以下内容：

gain notebook 数据访问逻辑摘要

与 dark count 数据访问方式的差异分析

修改/新增文件列表

reader 重构说明

完整代码

运行方式

风险点与依赖说明

验收标准
程序能够在 gain 场景下读取并准备分析输入，而不是停留在 dark count 专用结构上。

任务 7：实现 SPE gain 分析模块
任务目标
基于 example_code/pmt_gain_example.ipynb 实现结构化的 SPE gain 分析模块，包括默认积分窗口、单高斯拟合和结果输出。

需要 Agent 阅读的内容
example_code/pmt_gain_example.ipynb

已完成的 reader 抽象

pipeline 和 models 代码

已知需求
输入默认的积分窗口区间

以单高斯模拟

给出初始参数值

输出最佳高斯拟合参数

具体要求
请完成以下内容：

新增或完善：

src/pmt_analysis/analysis/spe_gain.py

定义 SpeGainResult 数据结构

抽取 notebook 中：

积分窗口处理逻辑

拟合输入数据准备逻辑

单高斯拟合逻辑

至少输出以下内容：

run_id

pmt_id

gain

fit_mean

fit_sigma

fit_amplitude

fit_success

integration_window

必要 metadata

将结果接入 pipeline

在终端打印关键拟合结果

约束
必须优先遵循 notebook 的拟合思路

不要引入与当前需求无关的多高斯或复杂模型

拟合失败时要有明确标记，不要静默失败

若某些参数定义不够清楚，请在输出中注明假设

交付要求
请输出以下内容：

gain notebook 核心分析逻辑摘要

修改/新增文件列表

SpeGainResult 设计说明

完整代码

运行方式

拟合结果打印示例

当前假设与局限性

验收标准
运行后能够得到 SPE gain 相关拟合输出，而不是只停留在原始积分分布。

任务 8：为 SPE gain 增加验证图，并串联最小可用 pipeline
任务目标
完成 SPE gain 验证图输出，并将当前已有功能串联为“最小可用分析流程”。

需要 Agent 阅读的内容
analysis/spe_gain.py

plotting/validation.py

pipeline.py

cli.py

具体要求
请完成以下内容：

为 SPE gain 生成验证图，优先考虑：

积分分布直方图

高斯拟合叠加图

图片保存到 output_dir

图片文件名中包含：

run_id

spe_gain

将 SPE gain 图路径加入统一结果对象

完善 pipeline.py，使其支持：

读取 runinfo

读取原始数据

执行 dark count 分析

执行 SPE gain 分析

保存验证图

打印最终摘要

当前 APP 和数据库写入必须明确显示“未实现/待补充”

约束
不要伪造 APP 分析结果

不要伪造数据库写入逻辑

要确保当前最小 pipeline 可以完整运行到结果输出阶段

输出应结构化，便于后续写库

交付要求
请输出以下内容：

修改/新增文件列表

完整 pipeline 流程说明

完整代码

如何运行最小可用版本

最终终端摘要示例

当前尚未实现的功能列表

验收标准
我应该能够运行一次最小可用分析流程，获得：

dark count 参数输出

SPE gain 参数输出

对应验证图

明确的未实现提示（APP、数据库写入）

推荐执行顺序
请你按下面顺序逐条发给 Agent：

任务 1：初始化项目骨架与 CLI 入口

任务 2：实现 runinfo.json 解析层

任务 3：抽取 dark count notebook 的原始数据读取逻辑

任务 4：实现 dark count 分析模块

任务 5：为 dark count 增加验证图输出

任务 6：抽取 gain notebook 的数据读取差异与前置逻辑

任务 7：实现 SPE gain 分析模块

任务 8：增加 SPE gain 验证图并串联最小 pipeline

给你的使用建议