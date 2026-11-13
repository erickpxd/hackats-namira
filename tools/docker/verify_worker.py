"""Real, offline isolation/cancellation probe. Requires the built worker image.

Runs fixed diagnostic Python only; no target, network request, host mount or
additional capability. The application worker operation allowlist is unchanged.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from pentest_pipeline.execution.container_manager import (
    ContainerCancelled, ContainerConfig, DockerContainerManager, WORKER_COMMAND)

PROBE = r'''
import errno, json, os, pathlib, subprocess
p = pathlib.Path
status = dict(line.split(':', 1) for line in p('/proc/self/status').read_text().splitlines() if ':' in line)
out = {'uid': os.getuid(), 'gid': os.getgid(),
       'no_new_privs': int(status['NoNewPrivs']), 'seccomp': int(status['Seccomp']),
       'cap_eff': int(status['CapEff'].strip(), 16),
       'apparmor': p('/proc/self/attr/current').read_text().strip(),
       'read_only': bool(os.statvfs('/').f_flag & os.ST_RDONLY),
       'interfaces': sorted(os.listdir('/sys/class/net')),
       'memory_max': p('/sys/fs/cgroup/memory.max').read_text().strip(),
       'pids_max': p('/sys/fs/cgroup/pids.max').read_text().strip(),
       'cpu_max': p('/sys/fs/cgroup/cpu.max').read_text().strip(),
       'docker_socket': p('/var/run/docker.sock').exists() or p('/run/docker.sock').exists()}
test = p('/tmp/namira-noexec-probe')
test.write_text('#!/bin/sh\nexit 0\n')
test.chmod(0o700)
try:
    subprocess.run([str(test)], check=True)
    out['tmp_noexec'] = False
except OSError as exc:
    out['tmp_noexec'] = exc.errno == errno.EACCES
test.unlink()
print(json.dumps(out))
'''


def main():
    config = ContainerConfig()
    manager = DockerContainerManager()
    config.validate(allowed_images=manager.allowed_images)
    argv = manager._argv(config)[:-len(WORKER_COMMAND)] + ["python", "-I", "-c", PROBE]
    result = json.loads(manager._subprocess_runner(argv, b"", 15))
    assert result["uid"] == result["gid"] == 65534, result
    assert result["no_new_privs"] == 1 and result["seccomp"] == 2, result
    assert result["cap_eff"] == 0 and result["read_only"] and result["tmp_noexec"], result
    assert "docker-default" in result["apparmor"] and "enforce" in result["apparmor"], result
    assert result["interfaces"] == ["lo"] and not result["docker_socket"], result
    assert int(result["memory_max"]) == 256 * 1024 * 1024 and int(result["pids_max"]) == 128, result
    quota, period = map(int, result["cpu_max"].split())
    assert quota / period == 1, result

    stop = Event()
    manager = DockerContainerManager(stop_event=stop)
    label = "namira.isolation-probe=" + uuid4().hex
    argv = manager._argv(config)[:-len(WORKER_COMMAND)]
    argv[argv.index(config.image):argv.index(config.image)] = ["--label", label]
    argv += ["python", "-I", "-c", "import time; print('ready', flush=True); time.sleep(30)"]
    ready = False
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(manager._subprocess_runner, argv, b"", 15)
        try:
            deadline = monotonic() + 8
            while monotonic() < deadline:
                ids = subprocess.check_output(["docker", "ps", "-q", "--filter", "label=" + label], text=True).split()
                if ids and b"ready" in subprocess.check_output(["docker", "logs", ids[0]]):
                    ready = True
                    break
                if future.done():
                    break
                sleep(.1)
        finally:
            stop.set()
        try:
            future.result(timeout=12)
            raise AssertionError("Worker did not acknowledge cancellation")
        except ContainerCancelled:
            pass
    assert ready, "Cancellation must occur after Python starts"
    assert manager.cleanup_status == "completed"
    assert not subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=" + label]).strip()
    print(json.dumps({"isolation": result, "cancelled_after_start": True,
                      "cleanup_confirmed": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
