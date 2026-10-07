"""Read only process identity when Windows CIM access is unavailable."""

import json
import subprocess
import sys

import psutil


def main():
    try:
        process = psutil.Process(int(sys.argv[1]))
        # A missing/inaccessible command line is never enough evidence to stop a process.
        command_line = subprocess.list2cmdline(process.cmdline())
        if not command_line:
            return 1
        try:
            working_directory = process.cwd()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            working_directory = None
        print(json.dumps({
            "ProcessId": process.pid,
            "ParentProcessId": process.ppid(),
            "CommandLine": command_line,
            "WorkingDirectory": working_directory,
        }, ensure_ascii=True))
        return 0
    except (psutil.Error, ValueError, IndexError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
