from src.storage.db import SessionStorage
from src.text.edit_memory import EditMemoryApplier, MemoryRule


def test_confirmed_edit_saves_and_loads_memory_rule(tmp_path):
    storage = SessionStorage(tmp_path / "sessions.db")

    outcome = storage.save_confirmed_edit(
        session_id=7,
        source_kind="asr_text",
        before_text="请用EMG二点零生成图",
        after_text="请用image 2.0生成图",
        mode="cursor_prompt",
        output_script="simplified",
        metadata={"source": "test"},
    )

    assert outcome["edit_id"] > 0
    assert {"kind": "term_replacement", "pattern": "EMG二点零", "replacement": "image 2.0"} in outcome["learned_rules"]
    assert outcome["failure_sample"]["inferred_failure_type"] == "asr_term_error"
    assert outcome["failure_sample"]["should_add_regression"] is True

    rules = storage.load_memory_rules()
    assert rules == [
        MemoryRule(
            pattern="EMG二点零",
            replacement="image 2.0",
            mode="cursor_prompt",
            output_script="simplified",
        )
    ]
    result = EditMemoryApplier(rules).apply("帮我用EMG二点零生成分镜图", "cursor_prompt", "simplified")
    assert result.text == "帮我用image 2.0生成分镜图"
    assert result.applied[0]["pattern"] == "EMG二点零"

    failures = storage.recent_confirmed_edit_failures()
    assert len(failures) == 1
    assert failures[0]["record_id"] == 7
    assert failures[0]["source_kind"] == "asr_text"
    assert failures[0]["before_text"] == "请用EMG二点零生成图"
    assert failures[0]["after_text"] == "请用image 2.0生成图"
    assert failures[0]["inferred_failure_type"] == "asr_term_error"
    assert failures[0]["should_add_regression"] is True


def test_memory_applier_is_disabled_for_terminal_mode():
    applier = EditMemoryApplier([MemoryRule("EMG二点零", "image 2.0")])

    result = applier.apply("echo EMG二点零", "terminal_command", "simplified")

    assert result.text == "echo EMG二点零"
    assert result.applied == ()


def test_confirmed_edit_failure_detects_compiler_template_leak(tmp_path):
    storage = SessionStorage(tmp_path / "sessions.db")

    outcome = storage.save_confirmed_edit(
        session_id=8,
        source_kind="final_output",
        before_text="task_type=visual_generation\nroute_context: 任务路由与模板参考\n请覆盖以下要点。",
        after_text="请为 image 2.0 生成一条电商主图提示词，突出产品主体、光线和背景。",
        metadata={
            "debug": {
                "raw_asr_text": "帮我用 image 2.0 生成一张电商主图。",
                "cleaned_text": "帮我用 image 2.0 生成一张电商主图。",
                "final_text": "task_type=visual_generation\nroute_context: 任务路由与模板参考\n请覆盖以下要点。",
                "route": {"task_type": "visual_generation"},
                "intent_frame": {"task_hint": "visual_generation", "artifact_type": "image_prompt"},
                "quality_gate_attribution": {
                    "reason": "internal_prompt_leak",
                    "stage": "prompt_leak_guard",
                    "origin": "llm_internal_template_or_schema_leak",
                },
            }
        },
    )

    assert outcome["failure_sample"]["inferred_failure_type"] == "compiler_template_leak"
    assert outcome["failure_sample"]["should_add_regression"] is True
    failure = storage.recent_confirmed_edit_failures()[0]
    assert failure["final_text_before"].startswith("task_type=visual_generation")
    assert failure["route_before"]["task_type"] == "visual_generation"
    assert failure["intent_frame_before"]["artifact_type"] == "image_prompt"
    assert failure["quality_gate_attribution_before"]["stage"] == "prompt_leak_guard"


def test_confirmed_edit_failure_detects_paste_feedback_miss(tmp_path):
    storage = SessionStorage(tmp_path / "sessions.db")

    outcome = storage.save_confirmed_edit(
        session_id=9,
        source_kind="final_output",
        before_text="请优化语音指令编译器的输出质量。",
        after_text=(
            "请修复语音指令编译器的自动粘贴回归：录音处理完成后，"
            "最终提示词应自动粘贴到当前目标界面，并保持语音窗口位置。"
        ),
        metadata={
            "debug": {
                "raw_asr_text": "之前可以自动粘贴到目标界面，现在没有这个功能了，任务栏还得点一下。",
                "cleaned_text": "之前可以自动粘贴到目标界面，现在没有这个功能了，任务栏还得点一下。",
                "final_text": "请优化语音指令编译器的输出质量。",
                "route": {"task_type": "bug_report"},
                "intent_frame": {"task_hint": "bug_report", "artifact_type": "software_feedback"},
                "quality_gate_attribution": {
                    "reason": "missing_software_feedback_paste_context",
                    "stage": "software_feedback_guard",
                    "origin": "compiler_or_llm_missed_software_feedback",
                },
            }
        },
    )

    assert outcome["failure_sample"]["inferred_failure_type"] == "paste_feedback_missed"
    assert outcome["failure_sample"]["should_add_regression"] is True
    failure = storage.recent_confirmed_edit_failures()[0]
    assert failure["cleaned_text"].startswith("之前可以自动粘贴")
    assert failure["route_before"]["task_type"] == "bug_report"


def test_confirmed_edit_failure_detects_punctuation_or_wording_without_regression(tmp_path):
    storage = SessionStorage(tmp_path / "sessions.db")

    outcome = storage.save_confirmed_edit(
        session_id=10,
        source_kind="final_output",
        before_text="你好世界",
        after_text="你好，世界。",
        metadata={"debug": {"raw_asr_text": "你好世界", "cleaned_text": "你好世界", "final_text": "你好世界"}},
    )

    assert outcome["failure_sample"]["inferred_failure_type"] == "punctuation_or_wording"
    assert outcome["failure_sample"]["should_add_regression"] is False
    assert storage.recent_confirmed_edit_failures()[0]["should_add_regression"] is False
