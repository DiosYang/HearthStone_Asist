from hearthstone_assistant.prompt.system import SYSTEM_PROMPT


def profile(question):
    if any(word in question for word in ("卡牌", "卡名", "费用", "效果", "查询", "查一下", "查下", "card_id")):
        return "card_lookup"
    if any(word in question for word in ("套牌", "卡组", "留牌", "构筑")):
        return "deck_discussion"
    return "general"


def system_for(question):
    additions = {
        "general":"本轮以清楚回答问题为主；涉及具体卡牌事实时仍应调用卡牌工具，不因本轮标签是general就猜测。",
        "card_lookup":"本轮重点核对卡牌事实：先search_cards；唯一候选或用户指定ID后get_card。同名版本列出候选和系列，请用户澄清，不把候选中的任意一张当当前标准版本。",
        "deck_discussion":"本轮讨论套牌思路；涉及具体卡牌费用/效果时查询工具。没有完整牌表先澄清，不编套牌码、当前标准合法性、热度或胜率。"}
    return SYSTEM_PROMPT + "\n本轮任务补充：" + additions[profile(question)]
