"""Default design targets, not empirically calibrated Gaokao difficulty claims.

The policy changes runtime instructions only, never reviewed blueprint metadata.
"""
from copy import deepcopy

POLICY_VERSION = 'gaokao-design-v1'
SCHEDULES = {
    'single_choice': ['foundation'] * 4 + ['standard'] * 3 + ['advanced'],
    'multiple_choice': ['standard', 'advanced', 'challenge'],
    'fill_blank': ['foundation', 'standard', 'advanced'],
    'short_answer': ['standard', 'advanced', 'advanced', 'challenge', 'challenge'],
    'essay': ['standard', 'advanced', 'advanced', 'challenge', 'challenge'],
}
BANDS = {
    'foundation': {'label': '基础', 'reasoning_target': '考查一个核心概念及必要的定义域、条件辨识；通常1–2个关键推理环节，不靠无意义大数运算。'},
    'standard': {'label': '常规综合', 'reasoning_target': '联系两个相关知识点，包含建模、变形或条件转化；通常2–3个关键推理环节，不以直接代公式替代综合。'},
    'advanced': {'label': '进阶综合', 'reasoning_target': '要求较深的条件分析、数形结合、分类讨论或参数处理；通常3–4个关键环节，条件充分且可在高中课程范围解决。'},
    'challenge': {'label': '压轴探索', 'reasoning_target': '设置有梯度的探索或证明，要求发现结构、构造、分类完备性或必要充分性论证；难在思路而非生僻超纲知识和计算堆砌。'},
}


def difficulty_targets(blueprint):
    """Allocate by ordered occurrence within each type, not by printed numbers.

    The 8/3/3/5 shape maps exactly to the published policy schedule. Other
    shapes sample that type's schedule proportionately at interval midpoints.
    """
    grouped = {}
    for section in blueprint['sections']:
        for slot in section['slots']:
            grouped.setdefault(slot['type'], []).append((section['id'], slot['number']))
    result = {}
    for kind, keys in grouped.items():
        schedule = SCHEDULES.get(kind, ['foundation', 'standard', 'advanced', 'challenge'])
        for index, key in enumerate(keys):
            position = min(len(schedule)-1, ((2*index+1)*len(schedule))//(2*len(keys)))
            band = schedule[position]
            result[key] = {'policy': POLICY_VERSION, 'band': band, **deepcopy(BANDS[band]),
                           'calibration': '命题目标，非官方难度系数；须经真实试做数据校准。'}
    return result


AUTHOR_RULES = [
    '默认按高考数学模拟命题目标设计，不是低难度接口冒烟题。每个slot的difficulty是后端确定的设计目标，返工不能自行降档；它不是官方实测难度。',
    '严格遵守题位的题型、分值、选项标签、知识点与style_descriptors。题干用准确中文，明确变量范围、参数条件和所有必要定义；题号和分值不可改。',
    '新颖性来自情境、条件结构、考查角度或推理路径，不是照抄source_stem再换几个数；不要复用同组题的骨架或让另一题泄露本题答案。',
    '单选恰有一个正确项；多选至少两个正确项且不得全为显然结论。逐项验证选项，干扰项应对应合理错误，不出现等价重复选项。',
    '填空必须答案确定、单位和等价形式明确；解答题按分值设计有梯度的小问，给完整推导和建议分步评分，总评分不得超过该题位分值。',
    '先独立完成全部推导再提交答案，检查符号、定义域、边界、分类是否完备以及必要/充分性；不以数值试验替代证明。几何题没有实际图源时须用文字给出充分定义，不能引用不存在的图。',
    '接到feedback时只修复当前指定题位，逐条处理纠错意见并保持difficulty；不要重写已通过的其他题。返回结构化JSON，不提供可执行代码，不在题干泄露答案。',
]
REVIEW_RULES = [
    '按slot.difficulty的reasoning_target审核是否达到当前命题目标；基础与压轴不能仅靠题目篇幅区分。若只是直接代入公式而未达到指定推理层次，应拒绝并指出需要的改进。',
    '对照独立求解与出题者解析复核，不能仅因答案字符串相同就通过；检查逻辑、定义域、特殊值、分情况覆盖和证明完整性。不能确认时拒绝，不能替出题者补造条件。',
    '核对题型约束、单选唯一性、多选至少两个正确项、填空确定性、解答题梯度和分步评分；拒绝歧义、等价重复选项、题干泄露答案及缺失的图形条件。',
    'corrections逐条指向当前题位的具体条件、选项或推理步骤，说明何处错误及修复要求；不改题号、分值、题型或难度档，不重写其他题。',
]
