# pmt_analysis AI Agent 开发任务书

## 1. 项目名称
pmt_analysis

## 2. 项目目标
开发一个用于 PMT 测试数据分析的 Python 软件包与命令行工具，支持以下能力：

1. 输入单个 `run_id` 或多个 `run_id`
2. 根据 `runinfo.json` 或后续数据库 `tpc_runinfo` 的信息，识别运行类型与分析配置
3. 读取 PMT 原始二进制测试数据
4. 计算 PMT 关键参数：
   - dark count rate
   - single electron gain (SPE gain)
   - afterpulse probability (APP，后续补充)
5. 在写入数据库前打印关键参数，并生成验证图供用户检查
6. 用户确认结果合理后，执行数据库写入
7. 当前优先完成：
   - 项目骨架
   - runinfo 解析
   - 原始数据读取抽象
   - dark count rate 分析
   - SPE gain 分析
   - 验证图输出
8. APP 分析与数据库写入将在后续材料提供后接入

## 3. 当前已提供材料
项目目录下已有以下文件：

- `example_code/pmt_dark_cout_rate_example.ipynb`
- `example_code/pmt_gain_example.ipynb`
- `example_code/runinfo.json`

说明：
1. 两个 notebook 中包含原始数据访问与分析相关示例代码
2. `runinfo.json` 用于提供 run 的类型或分析相关配置示例
3. APP example notebook 与数据库写入 example code 暂未提供，当前阶段不得臆造最终数据库写入实现

## 4. 开发原则
AI Agent 必须遵守以下原则：

1. 优先复用 `example_code/` 下 notebook 的领域逻辑，不得随意改写关键物理分析逻辑
2. 优先将 notebook 代码整理为可复用的 Python 模块函数
3. 不要直接依赖 notebook 运行环境作为最终实现，必须抽象为包内模块
4. 所有分析流程必须能通过命令行调用
5. 所有核心分析函数应具备类型注解与简要 docstring
6. 所有关键步骤必须具备清晰日志输出
7. 写数据库前必须先有本地结果打印与验证图输出
8. 在数据库写入示例代码未提供前，只能预留接口，不可伪造真实写库逻辑
9. 当前代码需兼容 Python 3.9+
10. 运行环境为 Linux，当前不考虑 Windows
11. 当前不开发 GUI，但可以保留接口扩展位

## 5. 当前阶段必须实现的功能范围
### 5.1 输入能力
支持以下输入方式：
- 单个 `run_id`
- 多个 `run_id`
- 后续可扩展 `run_id` 文件输入

### 5.2 runinfo 获取
当前优先支持：
- 从 `example_code/runinfo.json` 解析示例 run 信息

后续可扩展：
- 从 `tpc_runinfo` 数据库获取

### 5.3 数据读取
必须从 notebook 示例中抽取原始数据访问方式，并整理成统一 reader 接口。

### 5.4 dark count rate 分析
根据示例 notebook 中现有逻辑实现：
- dark count 总数统计
- total daq run time length 获取
- dark count rate 计算
- asymmetry 判定
- 噪声过滤逻辑

当前已知规则：
- `dark count rate = total_dark_count / total_daq_run_time_length`
- `asymmetry = pulse_height / pulse_range`
- `asymmetry > 0.7` 判定为暗计数
- `asymmetry <= 0.7` 判定为噪声信号

### 5.5 SPE gain 分析
根据示例 notebook 中现有逻辑实现：
- 使用默认积分窗口
- 计算单光电子相关积分量
- 用单高斯进行拟合
- 输出最佳高斯参数
- 生成拟合验证图

### 5.6 验证输出
每次分析后必须：
- 打印关键参数值
- 输出必要的中间统计结果
- 生成验证图并保存到本地

### 5.7 数据库写入接口预留
当前只允许：
- 设计统一结果对象
- 设计数据库写入接口
- 使用 `NotImplementedError` 或占位实现

当前不允许：
- 自行假设数据库表结构并完成真实写入

## 6. 当前阶段不实现的内容
以下内容当前只保留扩展位，不进入正式实现：
- APP 分析逻辑
- 真实数据库写入
- GUI
- Web 服务
- 大规模并发分析
- 自动图表审核决策

## 7. 建议项目结构
建议使用以下结构：

```text
pmt_analysis/
├── pyproject.toml
├── README.md
├── example_code/
├── src/pmt_analysis/
│   ├── __init__.py
│   ├── cli.py
│   ├── pipeline.py
│   ├── config.py
│   ├── runinfo.py
│   ├── models.py
│   ├── io/
│   │   ├── __init__.py
│   │   └── raw_reader.py
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── dark_count.py
│   │   ├── spe_gain.py
│   │   └── afterpulse.py
│   ├── plotting/
│   │   ├── __init__.py
│   │   └── validation.py
│   └── db/
│       ├── __init__.py
│       └── writer.py
├── tests/
└── docs/


8. 代码规范要求
使用 Python 3.9+ 语法
遵循 PEP8
优先使用标准库与示例代码中已有依赖
核心函数添加类型注解
复杂分析逻辑前允许添加简短说明注释
不做无关重构
保持模块边界清晰：
    数据读取
    runinfo 解析
    分析逻辑
    绘图验证
    数据库写入接口

9. 建议统一数据模型
建议设计以下对象：

9.1 RunInfo
统一描述一个 run 的基本信息：
run_id
data_type
file_path 或原始数据定位信息
配置参数
元信息来源（json/db）

9.2 PMTAnalysisResult
统一描述单个 PMT 或单次分析输出：
run_id
pmt_id
analysis_type
metrics
summary
validation_plot_paths
status
raw_metadata

9.3 AnalysisBundle
描述单个 run 的汇总结果：
run_id
runinfo
dark_count_results
spe_gain_results
afterpulse_results
plots
ready_for_db

10. CLI 要求
建议提供如下命令形式：
    pmt-analysis analyze --run-id 12345
    pmt-analysis analyze --run-id 12345 12346 12347

建议支持参数：

--run-id

--runinfo-file

--output-dir

--save-plots

--no-plots

--print-summary

后续可扩展：

--write-db

--confirm

11. 开发任务执行方式
AI Agent 必须分阶段提交结果，每阶段输出以下内容：

本次修改文件列表

核心实现说明

使用方式

已完成内容

未完成内容

风险点

验证方式

12. 当前阶段推荐执行顺序
建立项目骨架与 CLI

解析 runinfo.json

抽取 notebook 中的数据读取逻辑

实现 dark count 分析模块

实现 SPE gain 分析模块

实现验证图输出

建立 pipeline 串联流程

补充基础测试

为 APP 与 DB 写入预留接口

13. 验收标准
当前阶段验收以“能跑通 + 结果可检查”为准：

能用命令行输入 run_id

能正确读取 runinfo.json

能调用 notebook 抽取后的读取逻辑访问数据

能输出 dark count rate 分析结果

能输出 SPE gain 分析结果

能生成并保存验证图

输出结果结构统一

不进行真实数据库写入

APP 模块明确标记为待实现

14. 禁止事项
不得在未阅读 notebook 的情况下凭空重写分析算法

不得伪造数据库写入实现

不得混杂 notebook 风格临时代码到最终库接口中

不得将所有逻辑堆在单文件中

不得跳过关键参数打印与验证图输出

15. 后续待补材料
后续将补充以下材料，届时需增量开发：

APP example notebook

数据库写入 example code

更多 runinfo 或数据类型样例