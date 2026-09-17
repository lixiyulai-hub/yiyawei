from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_launcher_restarts_itself_hidden_and_hides_ollama_console():
    script = (ROOT / "scripts" / "Start-VoicePromptCompiler.ps1").read_text(encoding="utf-8")

    assert "[switch]$Hidden" in script
    assert 'Start-Process -FilePath "powershell.exe"' in script
    assert "-WindowStyle Hidden" in script
    assert 'Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden' in script
    assert '& $Python "app.py" "--gui"' in script
