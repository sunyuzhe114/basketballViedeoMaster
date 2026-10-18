"""Exercise the actual Windows entry points without opening or editing user projects."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BAT = ROOT / "启动篮球剪辑大师.bat"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launcher")


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "启动测试 with spaces & (test)!"
    package = root / "basketball_master"
    package.mkdir(parents=True)
    shutil.copy2(BAT, root / BAT.name)
    shutil.copy2(ROOT / "basketball_master/launch.ps1", package / "launch.ps1")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({'python': sys.executable, 'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n"
        "sys.exit(int(os.environ.get('TEST_APP_EXIT', '0')))\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    for name in ("USERPROFILE", "LOCALAPPDATA", "ProgramData"):
        env[name] = str(tmp_path / name)
    aliases = Path(env["LOCALAPPDATA"]) / "Microsoft/WindowsApps"
    aliases.mkdir(parents=True)
    (aliases / "python.exe").write_bytes(b"must never execute the Store alias")
    env["PATH"] = str(aliases)
    return root, env


def run_launcher(launcher, *arguments):
    root, env = launcher
    command = subprocess.list2cmdline([str(root / BAT.name), *arguments])
    shell = subprocess.list2cmdline([os.environ["COMSPEC"]])
    return subprocess.run(
        f'{shell} /d /s /c "{command}"',
        cwd=root.parent, env=env, input="\n", capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def configure(launcher, path):
    root, _ = launcher
    (root / "basketball_master/python-path.txt").write_text(str(path), encoding="utf-8-sig")


def app_result(result):
    return next(json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"python"'))


@pytest.mark.parametrize("executable", ["python.exe", "pythonw.exe"])
def test_saved_runtime_wins_over_store_alias_and_forwards_arguments(launcher, executable):
    configure(launcher, Path(sys.executable).with_name(executable))
    result = run_launcher(launcher, "--example", "value with spaces")
    assert result.returncode == 0, result.stdout + result.stderr
    data = app_result(result)
    assert Path(data["python"]).samefile(sys.executable)
    assert Path(data["cwd"]) == launcher[0]
    assert data["args"] == ["--example", "value with spaces"]


@pytest.mark.parametrize("saved", [None, "missing/pythonw.exe", ""])
def test_path_fallback_skips_store_alias_and_stale_configuration(launcher, saved):
    if saved is not None:
        configure(launcher, launcher[0] / saved if saved else "")
    launcher[1]["PATH"] += os.pathsep + str(Path(sys.executable).parent)
    result = run_launcher(launcher)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(app_result(result)["python"]).samefile(sys.executable)


def test_application_failure_is_preserved(launcher):
    configure(launcher, sys.executable)
    launcher[1]["TEST_APP_EXIT"] = "7"
    result = run_launcher(launcher)
    assert result.returncode == 7, result.stdout + result.stderr


def test_no_real_python_reports_actionable_error_without_store(launcher):
    result = run_launcher(launcher, "-CheckPython")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Python 3.10+" in result.stdout + result.stderr
    assert "python-path.txt" in result.stdout + result.stderr
    assert "Python was not found; run without arguments" not in result.stdout + result.stderr


def test_check_python_does_not_run_application(launcher):
    configure(launcher, sys.executable)
    result = run_launcher(launcher, "-CheckPython")
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(Path(sys.executable)) in result.stdout
    assert '{"python"' not in result.stdout
