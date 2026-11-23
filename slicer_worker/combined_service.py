"""One container, two isolated child services, fail-closed supervision.

The container PID 1 has only SETUID/SETGID capabilities to spawn separate
unprivileged identities. The worker cannot modify the shared engine store:
its UID differs from the store owner, and worker egress connect() is blocked
by a permanent Linux seccomp filter inherited by slicer executables.
"""
import ctypes
import errno
import os
import platform
import signal
import subprocess
import sys
import time


WORKER_UID = 10001
INSTALLER_UID = 10002
INSTALLER_STORE = "/opt/engine-store"


class SockFilter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]


class SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort),
                ("filter", ctypes.POINTER(SockFilter))]


def block_worker_outbound_connections():
    """Refuse all worker-initiated TCP/UDP/UNIX connects, even from AppImages.

    Only amd64 Linux is approved by the pinned slicer image. Failure to
    install this process-inherited restriction means the worker MUST NOT run.
    The HTTP listener still binds and accepts connections from MakerVault.
    """
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise RuntimeError("Restricted slicer supports Linux AMD64 only.")
    lib = ctypes.CDLL(None, use_errno=True)
    lib.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                          ctypes.c_ulong, ctypes.c_ulong]
    lib.prctl.restype = ctypes.c_int
    # On x86_64 connect(2) is syscall 42. seccomp_data.nr is at byte 0.
    program = (SockFilter * 4)(
        SockFilter(0x20, 0, 0, 0),
        SockFilter(0x15, 0, 1, 42),
        SockFilter(0x06, 0, 0, 0x00050000 | errno.EPERM),
        SockFilter(0x06, 0, 0, 0x7fff0000),
    )
    prog = SockFprog(len(program), program)
    if lib.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Worker no_new_privs failed")
    ptr = ctypes.addressof(prog)
    if lib.prctl(22, 2, ptr, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Worker outbound seccomp filter failed")


def run_worker():
    # Running this inside the worker subprocess, rather than the parent,
    # avoids restricting the installer or the health-monitoring parent.
    block_worker_outbound_connections()
    from .service import main
    main()


def run_installer():
    from .engine_installer_service import main
    main()


def _spawn(module, uid, env):
    return subprocess.Popen(
        [sys.executable, "-m", "slicer_worker.combined_service", module],
        user=uid, group=uid, env=env, start_new_session=True,
        stdin=subprocess.DEVNULL,
    )


def supervise():
    if os.geteuid() != 0:
        raise SystemExit("Slicer supervisor requires limited root for UID separation.")
    if not os.path.isdir(INSTALLER_STORE):
        raise SystemExit("Persistent slicer engine store is missing.")
    stat = os.stat(INSTALLER_STORE)
    if stat.st_uid != INSTALLER_UID or stat.st_mode & 0o022:
        raise SystemExit("Slicer store must be owned by installer UID 10002 and not group/world writable.")
    worker_env = os.environ.copy()
    worker_env.pop("SLICER_INSTALLER_TOKEN", None)
    installer_env = os.environ.copy()
    installer_env.pop("SLICER_WORKER_TOKEN", None)
    installer_env.pop("SLICER_ENGINES_JSON", None)
    children = []
    stopping = False

    def stop(_signal=None, _frame=None):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        # The worker can read the shared store, but only installer UID can
        # write it. The installer cannot read the worker's authentication token.
        children.append(_spawn("worker", WORKER_UID, worker_env))
        children.append(_spawn("installer", INSTALLER_UID, installer_env))
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Combined slicer child stopped unexpectedly.")
            time.sleep(0.5)
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "worker":
        run_worker()
    elif len(sys.argv) == 2 and sys.argv[1] == "installer":
        run_installer()
    elif len(sys.argv) == 1:
        supervise()
    else:
        raise SystemExit("Invalid combined slicer service mode.")


if __name__ == "__main__":
    main()
