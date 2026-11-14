# 中文数学试卷 LaTeX 样式 · 2026 新课标Ⅰ卷体例

- exam-layout.sty：通用排版（A4、页眉页脚、分页、连续题号、分区、分值、选项、可选答题框与答案模式），不写题目。
- paper-i2026.tex：本卷卷头和学生/答案入口；questions.tex 是 19 道原创示例题及 TikZ 图；key.tex 是独立解析。
- student.tex 与 answers.tex：分别编译学生题本、答案册。另附 generic-example.tex 是不带固定考试规格的短样例。
- 参照卷面结构，非真题，不声称复现真实难度。新课标Ⅰ卷体例：单选 8×5，多选 3×6，填空 3×5，解答 13/15/15/17/17 分，总分 150，120 分钟。题本不附答题卡。

依据：教育部考试院公开评析（https://www.moe.gov.cn/jyb_xwfb/xw_zt/moe_357/2026/2026_zt08/mtbd/202606/t20260610_1440059.html ）和可读的试卷转载（https://www.5ol.com/atta/202606/12/7b1fc8c01de65406485108b12b3e1854.html ）。转载用于核对页数、题号与分值，未转录真题。

用完整的 TeX Live 或 MiKTeX，使用 XeLaTeX 和 Noto/Fandol/宋体。每份运行两遍以更新总页数：
    xelatex -no-shell-escape student.tex
    xelatex -no-shell-escape student.tex
    xelatex -no-shell-escape answers.tex
    xelatex -no-shell-escape answers.tex

Agno 的 [Exam 导出](../exam-artifacts/)已复用这份样式。该静态样张用可信 LaTeX 编排公式；自动导出把经校验的模型/用户文本按字面转义，仅渲染明确允许的图形模板，不执行任意 LaTeX。
