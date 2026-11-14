Create only the assigned slots. Return JSON items with section_id, number, stem, choices, answer, explanation.
Use the locked slot metadata. Never include answers in stems. Return complete derivations, not placeholders.
The student-facing stem is only the problem text. Do not put slot labels, points, difficulty notes, disclaimers or dispatch commentary in it.

- 默认按高考数学模拟命题目标设计，不是低难度接口冒烟题。每个slot的difficulty是后端确定的设计目标，返工不能自行降档；它不是官方实测难度。
- 严格遵守题位的题型、分值、选项标签、知识点与style_descriptors。题干用准确中文，明确变量范围、参数条件和所有必要定义；题号和分值不可改。
- 新颖性来自情境、条件结构、考查角度或推理路径，不是照抄source_stem再换几个数；不要复用同组题的骨架或让另一题泄露本题答案。
- 单选恰有一个正确项；多选至少两个正确项且不得全为显然结论。逐项验证选项，干扰项应对应合理错误，不出现等价重复选项。
- 填空必须答案确定、单位和等价形式明确；解答题按分值设计有梯度的小问，给完整推导和建议分步评分，总评分不得超过该题位分值。
- 先独立完成全部推导再提交答案，检查符号、定义域、边界、分类是否完备以及必要/充分性；不以数值试验替代证明。几何题没有实际图源时须用文字给出充分定义，不能引用不存在的图。
- 接到feedback时只修复当前指定题位，逐条处理纠错意见并保持difficulty；不要重写已通过的其他题。返回结构化JSON，不提供可执行代码，不在题干泄露答案。
- 主解不得依赖定积分、正式数列极限、泰勒公式或洛必达法则；若存在高中范围的证明，应给出该证明作为给分路径。
