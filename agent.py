import os
import platform
import socket
import subprocess
from datetime import datetime, timezone

import psutil
import requests

# ================== CONFIG ==================
SERVER_URL = "http://192.168.10.203:9000/api/agent/report"
API_KEY = "NGUYENVANCAN-NKENGINEERING-919395DINHTHITHI"
APP_TITLE = "IT Device Info Agent"
# ============================================


# ---------- helpers ----------
def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return out.decode(errors="ignore").strip()
    except Exception:
        return ""


# ---------- CPU model (human readable) ----------
def get_cpu_model() -> str:
    sysname = platform.system()

    if sysname == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(cpu_name).strip()
        except Exception:
            pass

        cpu = platform.processor()
        return cpu.strip() if cpu else "Unknown CPU"

    if sysname == "Darwin":  # macOS
        # Intel Macs
        out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if out:
            return out
        # Apple Silicon fallback
        out = _run(["sysctl", "-n", "hw.model"])
        if out:
            return out
        return "Unknown CPU"

    # Linux/Ubuntu
    try:
        # /proc/cpuinfo is most available
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "model name" in line.lower():
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass

    out = _run(["lscpu"])
    if out:
        for line in out.splitlines():
            if "model name" in line.lower():
                return line.split(":", 1)[1].strip()

    cpu = platform.processor()
    return cpu.strip() if cpu else "Unknown CPU"


# ---------- RAM ----------
def get_ram_gb() -> float:
    return round(psutil.virtual_memory().total / (1024**3), 2)


# ---------- "SSD capacity": system disk total ----------
def get_system_disk_total_gb() -> float:
    sysname = platform.system()

    if sysname == "Windows":
        # system drive (usually C:)
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        try:
            total = psutil.disk_usage(drive).total
            return round(total / (1024**3), 2)
        except Exception:
            pass

        # fallback: sum fixed partitions
        total = 0
        for part in psutil.disk_partitions(all=False):
            try:
                total += psutil.disk_usage(part.mountpoint).total
            except Exception:
                pass
        return round(total / (1024**3), 2)

    # macOS/Linux: root volume
    try:
        total = psutil.disk_usage("/").total
        return round(total / (1024**3), 2)
    except Exception:
        return 0.0


# ---------- Wi-Fi MAC only ----------
def get_wifi_mac() -> str:
    sysname = platform.system()

    # macOS: most reliable via networksetup
    if sysname == "Darwin":
        for iface in ["en0", "en1"]:
            out = _run(["networksetup", "-getmacaddress", iface])
            # format: "Ethernet Address: xx:xx:xx:xx:xx:xx"
            if out and ":" in out:
                mac = out.split()[-1].strip()
                if len(mac) >= 11:
                    return mac.upper()
        return ""

    if_addrs = psutil.net_if_addrs()

    # Windows: choose interface name contains wifi keywords
    if sysname == "Windows":
        keywords = ["wi-fi", "wifi", "wireless", "wlan"]
        for iface, addrs in if_addrs.items():
            low = iface.lower()
            if any(k in low for k in keywords):
                for a in addrs:
                    mac = getattr(a, "address", "") or ""
                    if mac and len(mac) >= 11 and (":" in mac or "-" in mac):
                        return mac.upper()
        return ""

    # Linux: typical wifi interface names
    # prefer wlan0 or wlp*
    preferred = []
    for iface in if_addrs.keys():
        low = iface.lower()
        if low == "wlan0" or low.startswith("wlp"):
            preferred.append(iface)

    for iface in preferred:
        for a in if_addrs.get(iface, []):
            mac = getattr(a, "address", "") or ""
            if mac and len(mac) >= 11 and (":" in mac or "-" in mac):
                return mac.upper()

    return ""


# ---------- OS string ----------
def get_os_string() -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        ver = platform.mac_ver()[0] or platform.release()
        return f"macOS {ver}"
    return f"{sysname} {platform.release()}"


# ---------- collect machine info ----------
def collect_machine_info() -> dict:
    ssd_gb = get_system_disk_total_gb()
    return {
        "hostname": socket.gethostname(),
        "os": get_os_string(),
        "cpu_model": get_cpu_model(),
        "ram_gb": get_ram_gb(),
        # gửi cả 2 key để server nào cũng nhận được
        "ssd_total_gb": ssd_gb,
        "disk_total_gb": ssd_gb,
        "wifi_mac": get_wifi_mac(),
    }


def format_info(m: dict) -> str:
    return (
        "========== THÔNG TIN MÁY ==========\n"
        f"Hostname   : {m.get('hostname','')}\n"
        f"OS         : {m.get('os','')}\n"
        f"CPU        : {m.get('cpu_model','')}\n"
        f"RAM (GB)   : {m.get('ram_gb','')}\n"
        f"SSD (GB)   : {m.get('ssd_total_gb','')}\n"
        f"WiFi MAC   : {m.get('wifi_mac','')}\n"
        "==================================\n"
    )


def send_report(user_name: str, machine: dict) -> tuple[int, str]:
    payload = {
        "agentVersion": "3.0.0",
        "submittedAt": datetime.now(timezone.utc).isoformat(),
        "userInputName": user_name,
        "machine": machine,
    }
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    r = requests.post(SERVER_URL, json=payload, headers=headers, timeout=15)
    return r.status_code, r.text


# ================== GUI (Tkinter) with fallback ==================
def run_gui():
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    root = tk.Tk()
    root.title(APP_TITLE)

    tk.Label(root, text="Nhập tên / mã nhân viên:").pack(anchor="w", padx=10, pady=(10, 0))
    name_var = tk.StringVar()
    entry = tk.Entry(root, textvariable=name_var, width=45)
    entry.pack(fill="x", padx=10)

    info_box = scrolledtext.ScrolledText(root, height=12)
    info_box.pack(fill="both", expand=True, padx=10, pady=10)

    def refresh_info():
        m = collect_machine_info()
        root._machine = m
        info_box.delete("1.0", tk.END)
        info_box.insert(tk.END, format_info(m))

    def do_send():
        name = name_var.get().strip()
        if not name:
            messagebox.showerror("Lỗi", "Bạn chưa nhập tên.")
            return
        m = getattr(root, "_machine", None)
        if not m:
            refresh_info()
            m = getattr(root, "_machine", None)

        try:
            code, text = send_report(name, m)
            if code == 200:
                messagebox.showinfo("OK", "✅ Đã gửi thông tin cho bộ phận IT nhé")
            else:
                messagebox.showerror("Lỗi", f"Gửi thất bại ({code}): {text[:200]}")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    btns = tk.Frame(root)
    btns.pack(pady=(0, 10))

    tk.Button(btns, text="Lấy thông tin", command=refresh_info, width=16).pack(side="left", padx=5)
    tk.Button(btns, text="Gửi", command=do_send, width=10).pack(side="left", padx=5)

    refresh_info()
    entry.focus()
    root.mainloop()


def run_cli():
    name = input("Nhập tên / mã nhân viên rồi Enter: ").strip()
    if not name:
        print("❌ Chưa nhập tên")
        return
    m = collect_machine_info()
    print(format_info(m))

    try:
        code, text = send_report(name, m)
        if code == 200:
            print("✅ Đã gửi thông tin cho bộ phận IT nhé")
        else:
            print(f"❌ Gửi thất bại ({code}): {text}")
    except Exception as e:
        print("❌ Lỗi gửi dữ liệu:", e)

    input("Nhấn Enter để thoát...")


def main():
    # Try GUI; if Tkinter missing -> fallback CLI (so it never “mở rồi tắt” im lặng khi debug)
    try:
        run_gui()
    except Exception:
        # Tkinter missing or GUI init failed
        run_cli()


if __name__ == "__main__":
    main()
