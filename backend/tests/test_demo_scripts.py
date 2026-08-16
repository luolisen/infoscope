from pathlib import Path


def test_demo_script_guards_worker_liveness_and_pid_reuse() -> None:
    script = (Path(__file__).resolve().parents[2] / "scripts" / "demo.sh").read_text()

    assert 'process_matches "$STATE/worker.pid" "python -m infoscope.worker"' in script
    assert 'See %s/worker.log' in script
    assert 'ps -p "$pid" -o command=' in script
    assert 'uvicorn infoscope.api.app:app' in script
    assert 'python -m infoscope.worker' in script
