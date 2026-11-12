# 运行数据目录

服务端在这里创建SQLite账号/会话/偏好/缓存、卡牌快照，以及按用户ID/会话ID分目录的log.txt和JSONL。除本说明外默认被Git忽略，不上传GitHub。文本日志含对话和工具正文，属于私有资料。不要放Key；忽略Git不代表已经备份或加密。测试在独立临时目录运行，不修改个人数据。

cards/zhCN保存HearthstoneJSON中文可收藏卡牌的SHA256快照和manifest；记录来源、获取时间、Last-Modified和指纹，来源未给build时为null。同名卡需按ID区分，不能把快照等同于当前标准合法性、天梯胜率或酒馆战棋数据。具体命令见项目README。
