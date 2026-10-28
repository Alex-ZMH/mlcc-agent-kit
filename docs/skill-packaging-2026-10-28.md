# 多尺度 Agent 与独立 Skill 包装

0.60.0候选；沿用现有集成分支与0.59公共执行架构，本轮不改变科学代码、后处理、单位、QC或求解器环境，不提交科学作业。

## 当前组织

Agent标题、简介、推荐问题及正文体现多尺度，分别说明相场、RVE、FEM和SPICE的选择依据、输入类别、结果与边界，原子建模及DFT/MD说明保留在对应章节。

Bundle直接绑定八个Skill：原建模、DFT、MD、properties，加四个独立run-mlcc-phase-field/rve/fem/spice。旧总入口已撤销，不保留代理Skill。既有CLI兼容命令仍可使用。

四个新顶层Skill具备操作选择表、输入准备、创建与执行步骤、已保存性质读取和失败处理。七个模块深层Skill继续保存专业定义，顶层按方法链接它们；其旧独立框架run/worker流程已更新到TaskRecord/SiteRunner/Slurm。公共任务细节集中在mlcc-agent/skills/references/task-lifecycle.md。

properties保留原DFT/MD内容，只新增四个模块的结果导航。各模块已有指标、张量、有效材料文件、曲线和后处理继续作为权威来源；本轮不创建通用性质适配器、统一Study性质包或尺度传参。物理定义和科学阈值没有迁移到LLM。

## 验证与边界

test_skill_packaging.py检查Agent/Bundle与实际Skill文件一致、四模块26个真实操作在各自Skill中可导航、顶层及深层引用与锚点有效、文档命令能被现有CLI解析且不调用后端。另使用skill-creator的quick_validate检查四个新Skill及改动的properties Skill。

四项包装检查、五份Skill格式检查均通过。父项目119项公共回归通过：Windows挂载目录的首轮因临时文件I/O较慢而中止，随后同步并逐文件核对公共源码/测试/schema到WSL原生目录，按相同默认命令完成。日志及机器摘要见verification/skill-packaging-2026-10-28/。

这属于静态安装材料与接口验证；未调用在线LLM，未验收私有Zeus实际加载和自然语言路由，也没有新的科学计算/精度验收。历史计算证据及0.59的DFT/MD环境缺项保留在原报告中。实际宿主安装后须确认八Skill可选、相关深层文档可读、同任务追问只读。
