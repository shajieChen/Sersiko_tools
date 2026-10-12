import os, socket, subprocess, sys, time

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(TOOL, "preview", "server.py")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def first_free_port(start, count=20):
    for port in range(start, start + count):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        else:
            return port
        finally:
            sock.close()
    return None



def is_preview_server_command(command, tool):
    if not command:
        return False
    folded = os.path.normcase(command.replace("/", os.sep))
    server = os.path.normcase(os.path.normpath(os.path.join(tool, "preview", "server.py")))
    relative = os.path.normcase(os.path.join("preview", "server.py"))
    return server in folded or relative in folded


def stop_preview_servers(processes, tool, kill):
    for pid, command in processes:
        if is_preview_server_command(command, tool):
            kill(pid)


def list_preview_processes():
    completed = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | ForEach-Object { $_.ProcessId.ToString() + [char]9 + $_.CommandLine }",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    processes = []
    for line in completed.stdout.splitlines():
        pid, sep, command = line.partition(chr(9))
        if sep and pid.strip().isdigit():
            processes.append((int(pid.strip()), command))
    return processes


def kill_pid(pid):
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_built():
    projects = [
        (os.path.join(TOOL, "tools", "RigDump", "RigDump.csproj"), os.path.join(TOOL, "tools", "RigDump", "bin", "Release", "net10.0", "RigDump.exe")),
        (os.path.join(TOOL, "tools", "Assemble", "Assemble.csproj"), os.path.join(TOOL, "tools", "Assemble", "bin", "Release", "net10.0", "Assemble.exe")),
    ]
    for project, exe in projects:
        if os.path.isfile(exe):
            continue
        print("正在编译 " + os.path.basename(project))
        subprocess.check_call(["dotnet", "build", project, "-c", "Release"])


def main():
    stop_preview_servers(list_preview_processes(), TOOL, kill_pid)
    port = first_free_port(8765)
    if port is None:
        print("从 8765 开始的端口都已被占用。")
        return 1
    ensure_built()
    subprocess.Popen(
        [sys.executable, SERVER, str(port)],
        cwd=TOOL,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                break
        except OSError:
            time.sleep(0.2)
    else:
        print("预览没有启动。")
        return 1
    os.startfile("http://127.0.0.1:%d/index.html" % port)
    if port == 8765:
        print("预览已打开。")
    else:
        print("8765 已被占用，预览改用 %d。" % port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
