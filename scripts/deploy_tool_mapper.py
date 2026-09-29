#!/usr/bin/env python3
import urllib.request
import json
import base64
import sys
import os

PRINTER_IP = "192.168.1.168"
API_URL = f"http://{PRINTER_IP}/server/ace/test_detect"

def run_remote_cmd(cmd: str):
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"cmd": cmd}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("result", {})

def upload_file(local_path: str, remote_path: str):
    with open(local_path, "rb") as f:
        content = f.read()
    b64 = base64.b64encode(content).decode("ascii")
    # write in chunks if needed or all at once
    cmd = f"echo '{b64}' | base64 -d > {remote_path}"
    res = run_remote_cmd(cmd)
    if res.get("returncode") != 0:
        raise RuntimeError(f"Failed to upload {local_path} -> {remote_path}: {res}")
    print(f"Successfully uploaded {local_path} -> {remote_path} ({len(content)} bytes)")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = " ".join(sys.argv[1:])
        print(f"Running: {cmd}")
        res = run_remote_cmd(cmd)
        print(res.get("output", ""))
    else:
        print("Usage: deploy_tool_mapper.py <remote_command>")
