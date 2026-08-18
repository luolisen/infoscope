from pathlib import Path


def test_demo_script_guards_worker_liveness_and_pid_reuse() -> None:
    script = (Path(__file__).resolve().parents[2] / "scripts" / "demo.sh").read_text()

    assert 'process_matches "$STATE/worker.pid" "python -m infoscope.worker"' in script
    assert 'process_matches "$STATE/api.pid" "uvicorn infoscope.api.app:app"' in script
    assert 'See %s/worker.log' in script
    assert 'ps -p "$pid" -o command=' in script
    assert 'ps -p "$1" -o lstart=' in script
    assert 'recorded_started_at=$(sed -n \'2p\'' in script
    assert 'Port %s is occupied by an unmanaged process' in script
    assert 'Health response did not come from this Demo API process' in script
    assert 'until health_has_worker' in script
    assert 'api: stale PID file' in script
    assert 'api: stale PID file; unmanaged process on port %s' in script
    assert 'api: unmanaged process on port %s' in script
    assert 'uvicorn infoscope.api.app:app' in script
    assert 'python -m infoscope.worker' in script
    assert '--check-research-capability' in script
    assert 'Research capability unavailable; direct Ask remains available.' in script
