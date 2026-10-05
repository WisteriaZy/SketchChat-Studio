"""Literal, prefix-only expression tags shared by validation and chat parsing."""


def validate_tag(tag):
    if not isinstance(tag, str) or not tag or tag != tag.strip() or any(ord(c) < 32 or ord(c) == 127 for c in tag):
        raise ValueError('聊天标签不能为空、不能含首尾空白或控制字符；可用 /开心、[开心]、:) 等自定义格式')
    return tag
