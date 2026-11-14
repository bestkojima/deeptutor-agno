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
