"""ChatAgent - 降级提示词。"""

# Level 2 降级提示
FALLBACK_LEVEL_2_PROMPT = (
    "\n\n当前未检索到相关会议记录，但有一些历史对话可供参考。"
    "请基于历史对话和你的知识尽量帮助用户。如果确实无法回答，请礼貌说明。"
)

# Level 3 降级提示
FALLBACK_LEVEL_3_PROMPT = (
    "\n\n当前没有会议记录可供查询，也没有历史对话。"
    "请告知用户：当前没有会议记录可供查询，请先选择一个会议的录音或转录结果，我才能帮你分析。"
)

# Level 1 用户通知
LEVEL_1_USER_NOTICE = "未检索到相关会议记录，以下基于已有对话记录为您作答："

# Level 2 用户通知
LEVEL_2_USER_NOTICE = "当前没有会议记录可供查询，请先选择会议的录音或转录结果，我才能帮您分析。"


def determine_fallback_level(
    has_meeting: bool,
    has_kb: bool,
    has_history: bool,
    has_memory: bool = False,
) -> tuple[int, str | None]:
    """
    根据检索结果确定降级等级和用户提示语。

    Returns:
        (fallback_level, user_notice | None)
        fallback_level: 0=完整, 1=部分, 2=仅历史/记忆, 3=仅提示词
    """
    if has_meeting or has_kb:
        if has_meeting and has_kb:
            return 0, None
        else:
            return 1, None
    elif has_history or has_memory:
        return 2, LEVEL_1_USER_NOTICE
    else:
        return 3, LEVEL_2_USER_NOTICE
