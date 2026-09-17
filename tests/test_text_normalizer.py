from src.text.normalizer import normalize_output_text


def test_convert_traditional_to_simplified_and_punctuate_question():
    text = normalize_output_text("你能聽見我說話嗎,你看,你看一看,今天是星期幾", "simplified")
    assert "听见" in text
    assert "星期几" in text
    assert "？" in text


def test_keep_english_words_when_punctuating():
    text = normalize_output_text(
        "你要 Korea 这个我已经做出来了 就是 Cursor 插件已经在本地跑上了",
        "simplified",
    )
    assert "Korea" in text
    assert "Cursor" in text
    assert "你要 Korea 这个我已经做出来了" in text
    assert "就是 Cursor 插件已经在本地跑上了" in text
    assert "。" in text or "，" in text


def test_convert_simplified_to_traditional():
    text = normalize_output_text("你能听见 Cursor 和 Korea 吗？", "traditional")
    assert "聽見" in text
    assert "Cursor" in text
    assert "Korea" in text


def test_keep_structured_task_lines():
    text = normalize_output_text("目标：整理文本\n限制条件：不要生成代码", "simplified")
    assert "目标：" in text
    assert "\n" in text
    assert "限制条件：" in text


def test_keep_markdown_list_prefixes_clean():
    text = normalize_output_text("请覆盖以下要点：\n- 明确图片用途\n- 补齐画面风格", "simplified")

    assert "- 明确图片用途" in text
    assert "- 补齐画面风格" in text
    assert "-，" not in text


def test_normalize_output_text_collapses_repeated_punctuation():
    text = normalize_output_text("帮我看看，，，这个页面。。。", "simplified")

    assert "，，" not in text
    assert "。。" not in text


def test_insert_pause_for_security_copy():
    text = normalize_output_text(
        "高级安全设置,高级账户安全通过要求使用安全性更强的登录方式,并应用更严格的保护措施,来提供最高级别的账户安全帮助防止未经授权的访问。",
        "simplified",
    )
    assert text.startswith("高级安全设置。")
    assert "账户安全，帮助防止" in text


def test_no_comma_before_semicolon_in_constraints():
    text = normalize_output_text("限制条件：不是普通语音转文字；不是机器人聊天；不是代码生成器。", "simplified")
    assert "，；" not in text
    assert "不是普通语音转文字；" in text


def test_normalize_security_copy_correction_tail():
    text = normalize_output_text("高级安全设置 高级账户安全通过要求使用安全性更强的登陆方式 并用更严格的保护措施 来提供最高级的账户安全 帮助防止未经授权的访问。", "simplified")
    assert "防范，防止" not in text
    assert "帮助防止未经授权的访问" in text
    assert "登录方式" in text
    assert text.startswith("高级安全设置。")
    assert "登录方式，并用" in text


def test_preserve_image_two_zero_and_ratio_tokens():
    text = normalize_output_text("请使用 image二点零 生成 16:9 比例的分镜图", "simplified")

    assert "image 2.0" in text
    assert "image。2.0" not in text
    assert "16:9" in text
    assert "16: 9" not in text


def test_normalize_spoken_mg_two_as_image_two_zero():
    text = normalize_output_text("那个页MG二帮我生成一套AI短剧分镜图", "simplified")

    assert "image 2.0" in text
    assert "页MG二" not in text


def test_normalize_spoken_emg_two_zero_as_image_two_zero():
    text = normalize_output_text("那个那个EMG二点零，帮我生成连续分镜图", "simplified")

    assert "image 2.0" in text
    assert "EMG二点零" not in text


def test_normalize_spoken_img_two_zero_as_image_two_zero():
    text = normalize_output_text("帮我做一个PPT和一张图，用im g二点零帮我生成一张图，需要格式是十六比九的。", "simplified")

    assert "image 2.0" in text
    assert "im g二点零" not in text


def test_normalize_short_distance_is_not_rewritten_as_short_drama():
    text = normalize_output_text("这个短距离传输方案先解释一下", "simplified")

    assert "短距离传输" in text
    assert "短剧离" not in text
