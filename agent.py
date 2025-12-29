import os
import platform
import socket
import subprocess
from datetime import datetime, timezone

# Cần cài thư viện: pip install psutil requests
import psutil
import requests

# ================== CONFIG ==================
SERVER_URL = "http://192.168.10.203:9000/api/agent/report"
API_KEY = "NGUYENVANCAN-NKENGINEERING-919395DINHTHITHI"
APP_TITLE = "IT Device Info Agent v3.1" # Update version

# Đường dẫn tuyệt đối cho lệnh macOS (Quan trọng để fix lỗi .app)
MAC_CMD_SYSCTL = "/usr/sbin/sysctl"
MAC_CMD_NETSETUP = "/usr/sbin/networksetup"
# ============================================


# ---------- Helpers ----------
def _run(cmd: list[str]) -> str:
    """Chạy lệnh shell an toàn, ẩn window trên Windows"""
    try:
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        out = subprocess.check_output(
            cmd, 
            stderr=subprocess.DEVNULL, 
            startupinfo=startupinfo
        )
        return out.decode(errors="ignore").strip()
    except Exception:
        return ""


# ---------- 1. CPU (cpu_model) ----------
def get_cpu_model() -> str:
    sysname = platform.system()

    if sysname == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(cpu_name).strip()
        except:
            pass

    if sysname == "Darwin":
        # Dùng đường dẫn tuyệt đối
        out = _run([MAC_CMD_SYSCTL, "-n", "machdep.cpu.brand_string"])
        if out: return out
        out = _run([MAC_CMD_SYSCTL, "-n", "hw.model"]) 
        if out: return out

    # Linux fallback
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "model name" in line.lower():
                    return line.split(":", 1)[1].strip()
    except:
        pass
        
    return platform.processor() or "Unknown CPU"


# ---------- 2. RAM (ram_gb) ----------
def get_ram_gb() -> float:
    try:
        return round(psutil.virtual_memory().total / (1024**3), 2)
    except:
        return 0.0


# ---------- 3. Disk (disk_total_gb) ----------
def get_disk_gb() -> float:
    try:
        sysname = platform.system()
        if sysname == "Windows":
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            total = psutil.disk_usage(drive).total
        else:
            total = psutil.disk_usage("/").total
        return round(total / (1024**3), 2)
    except:
        return 0.0


# ---------- 4. MAC Address (wifi_mac) - ĐÃ FIX LỖI ----------
def get_mac_address() -> str:
    """
    Logic: Ưu tiên tìm đúng interface thực (en0 trên Mac), tránh MAC ảo (bridge).
    """
    sysname = platform.system()

    # --- BƯỚC 1: Dùng lệnh hệ thống macOS để lấy en0 (Chính xác nhất) ---
    if sysname == "Darwin":
        # Ưu tiên en0 (Wifi) rồi đến en1 (Ethernet)
        for port in ["en0", "en1"]:
            out = _run([MAC_CMD_NETSETUP, "-getmacaddress", port])
            # Output mẫu: "Ethernet Address: f8:73:df:..."
            if "Ethernet Address:" in out:
                mac = out.split("Ethernet Address:")[-1].strip()
                if len(mac) >= 11:
                    return mac.upper()

    # --- BƯỚC 2: Dùng psutil (Windows/Fallback Mac) ---
    try:
        if_addrs = psutil.net_if_addrs()
    except:
        return "Unknown MAC"

    # Danh sách tên interface ưu tiên
    priority_names = ["en0", "en1", "wlan0", "wi-fi", "wireless", "eth0", "ethernet"]
    
    # 2a. Quét tìm tên ưu tiên trước
    for name in priority_names:
        for oname in if_addrs.keys():
            if name in oname.lower():
                for snic in if_addrs[oname]:
                    if snic.family == psutil.AF_LINK:
                        mac = snic.address
                        if mac and len(mac) >= 11:
                            return mac.upper()

    # 2b. Nếu không thấy, quét tất cả nhưng LOẠI BỎ rác (bridge, vmnet...)
    skip_keywords = ["bridge", "vmnet", "vbox", "virtual", "utun", "awdl", "llw", "loopback"]
    
    for iface, snics in if_addrs.items():
        if any(skip in iface.lower() for skip in skip_keywords):
            continue
            
        for snic in snics:
            if snic.family == psutil.AF_LINK:
                mac = snic.address
                if mac and len(mac) >= 11 and mac != "00:00:00:00:00:00":
                    return mac.upper()

    return "Unknown MAC"


# ---------- OS String (os) ----------
def get_os_string() -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        ver = platform.mac_ver()[0] or platform.release()
        return f"macOS {ver}"
    return f"{sysname} {platform.release()}"


# ---------- TỔNG HỢP & GỬI ----------
def collect_full_info() -> dict:
    return {
        "hostname": socket.gethostname(),
        "os": get_os_string(),
        "cpu_model": get_cpu_model(),
        "ram_gb": get_ram_gb(),
        "disk_total_gb": get_disk_gb(),
        "wifi_mac": get_mac_address(),
    }


def format_display_text(m: dict) -> str:
    # Hiển thị lên màn hình App
    return (
        "========== THÔNG TIN THIẾT BỊ ==========\n"
        f"1. Tên máy (hostname)    : {m['hostname']}\n"
        f"2. Hệ điều hành (os)     : {m['os']}\n"
        f"3. CPU (cpu_model)       : {m['cpu_model']}\n"
        f"4. RAM (ram_gb)          : {m['ram_gb']} GB\n"
        f"5. Disk (disk_total_gb)  : {m['disk_total_gb']} GB\n"
        f"6. MAC (wifi_mac)        : {m['wifi_mac']}\n"
        "=======================================\n"
    )


def send_to_server(user_name: str, data: dict) -> tuple[int, str]:
    # Chuẩn bị payload khớp 100% với cột Database
    machine_payload = {
        "hostname": data["hostname"],
        "os": data["os"],
        "cpu_model": data["cpu_model"],
        "ram_gb": data["ram_gb"],
        "disk_total_gb": data["disk_total_gb"], # Key này phải khớp tên cột DB
        "wifi_mac": data["wifi_mac"]            # Key này phải khớp tên cột DB
    }

    payload = {
        "agentVersion": "3.1.0",
        "submittedAt": datetime.now(timezone.utc).isoformat(),
        "userInputName": user_name,
        "machine": machine_payload
    }
    
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    try:
        r = requests.post(SERVER_URL, json=payload, headers=headers, timeout=20)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


# ================== GUI PROGRAM ==================
def run_app():
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    root = tk.Tk()
    root.title(APP_TITLE)
    
    w, h = 600, 450
    ws, hs = root.winfo_screenwidth(), root.winfo_screenheight()
    x, y = (ws/2) - (w/2), (hs/2) - (h/2)
    root.geometry(f'{w}x{h}+{int(x)}+{int(y)}')

    lbl_frame = tk.Frame(root)
    lbl_frame.pack(fill="x", padx=10, pady=10)
    
    tk.Label(lbl_frame, text="Nhập Tên / Mã Nhân Viên:", font=("Arial", 10, "bold")).pack(side="left")
    
    name_var = tk.StringVar()
    entry_name = tk.Entry(lbl_frame, textvariable=name_var, font=("Arial", 11))
    entry_name.pack(side="left", fill="x", expand=True, padx=(10, 0))
    entry_name.focus()

    txt_info = scrolledtext.ScrolledText(root, font=("Consolas", 10), height=15)
    txt_info.pack(fill="both", expand=True, padx=10, pady=5)

    def load_data():
        txt_info.delete("1.0", tk.END)
        txt_info.insert(tk.END, "Đang quét thông tin phần cứng...\n")
        root.update()
        
        data = collect_full_info()
        root._scanned_data = data 
        
        display_str = format_display_text(data)
        txt_info.delete("1.0", tk.END)
        txt_info.insert(tk.END, display_str)

    def on_send():
        name = name_var.get().strip()
        if not name:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập tên/mã nhân viên!")
            entry_name.focus()
            return
            
        if not hasattr(root, "_scanned_data"):
            load_data()
            
        data = getattr(root, "_scanned_data")
        
        code, resp = send_to_server(name, data)
        if code == 200:
            messagebox.showinfo("Thành công", "✅ Đã gửi báo cáo thành công!")
        else:
            messagebox.showerror("Thất bại", f"Lỗi gửi (Code {code}):\n{resp}")

    btn_frame = tk.Frame(root, pady=10)
    btn_frame.pack(fill="x")

    btn_scan = tk.Button(btn_frame, text="🔄 Quét Lại", command=load_data, height=2, width=15)
    btn_scan.pack(side="left", padx=20)
    
    btn_send = tk.Button(btn_frame, text="📤 Gửi Báo Cáo", command=on_send, height=2, width=15, bg="#4CAF50", fg="white")
    btn_send.pack(side="right", padx=20)

    root.after(100, load_data)
    root.mainloop()

if __name__ == "__main__":
    run_app()