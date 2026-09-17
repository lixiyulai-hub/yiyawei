from src.text.filler_cleaner import clean_fillers
from src.text.recording_control import strip_trailing_recording_end_phrase
from src.text.self_correction import repair_spoken_self_corrections


def test_filler_cleaner_removes_obvious_fillers():
    text = clean_fillers("呃 这个，嗯，就是 帮我看一下。")
    assert "呃" not in text
    assert "嗯" not in text


def test_filler_cleaner_removes_adjacent_cjk_fillers():
    text = clean_fillers("嗯嗯啊啊，帮我看一下这个问题。")
    assert "嗯" not in text
    assert "啊" not in text
    assert "这个问题" in text


def test_filler_cleaner_removes_inline_breath_fillers():
    text = clean_fillers("系统就开始录音呃，或者说一个结束词。")
    assert "录音，或者说" in text
    assert "呃" not in text


def test_filler_cleaner_keeps_meaningful_this_phrase():
    text = clean_fillers("呃你帮我看一下这个接口，嗯，就是为什么返回空。")
    assert "这个接口" in text
    assert "为什么返回空" in text


def test_filler_cleaner_collapses_repeated_punctuation():
    text = clean_fillers("帮我看看，，，这个页面。。。")
    assert "，，" not in text
    assert "。。" not in text


def test_filler_cleaner_normalizes_spoken_noise_phrases():
    text = clean_fillers(
        "因为我不知道我们现在这个软件有不有呃这个功能，就是自动知道那个呃closer他反馈给我们就说没有额度了，需要切换了。然后，嗯，后台这个软件就能自适应的，呃，自己切换账号，注入账号就无感的嘛。"
    )
    assert "有不有" not in text
    assert "有没有" in text
    assert "呃" not in text
    assert "嗯" not in text
    assert "，，" not in text
    assert not text.endswith("嘛")


def test_self_correction_removes_previous_wrong_phrase():
    text, corrections = repair_spoken_self_corrections("不是聊天机器人，我说错了，不是机器人聊天，不是代码生成器。")
    assert "不是机器人聊天" in text
    assert "不是聊天机器人" not in text
    assert corrections


def test_self_correction_keeps_later_page_after_not_that():
    text, corrections = repair_spoken_self_corrections("帮我看一下这个登录页，不对不是登录页，是注册页，就是你先检查一下。")
    assert "注册页" in text
    assert "登录页" not in text
    assert corrections


def test_self_correction_repairs_er_not_with_later_fix():
    text, corrections = repair_spoken_self_corrections("而不是帮助防止未经授权的访问，刚才错了要改啊。")
    assert text == "防止未经授权的访问。"
    assert corrections


def test_self_correction_keeps_help_prevention_after_prior_wrong_phrase():
    text, corrections = repair_spoken_self_corrections("防范 而不是帮助防止未经授权的访问 刚才错了要改啊")
    assert text == "帮助防止未经授权的访问"
    assert corrections


def test_recording_control_strips_trailing_end_phrase():
    text, phrase = strip_trailing_recording_end_phrase("帮我检查登录页按钮状态，我说完了。")
    assert text == "帮我检查登录页按钮状态。"
    assert phrase == "我说完了"


def test_recording_control_keeps_meta_description():
    text, phrase = strip_trailing_recording_end_phrase("结束词就是我说完了。")
    assert text == "结束词就是我说完了。"
    assert phrase == ""
