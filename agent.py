import os
import platform
import socket
import subprocess
import json
from datetime import datetime, timezone

# Thư viện ngoài (cần pip install psutil requests)
import psutil
import requests

# ================== CONFIG ==================
SERVER_URL = "http://192.168.10.203:9000/api/agent/report"
API_KEY = "NGUYENVANCAN-NKENGINEERING-919395DINHTHITHI"
APP_TITLE = "IT Device Info Agent v3.0"

# --- Đường dẫn tuyệt đối cho macOS (Fix lỗi khi đóng gói .app) ---
MAC_CMD_SYSCTL = "/usr/sbin/sysctl"
MAC_CMD_PROFILER = "/usr/sbin/system_profiler"
MAC_CMD_NETSETUP = "/usr/sbin/networksetup"
# ============================================


# ---------- Helpers ----------
def _run(cmd: list[str]) -> str:
    """Chạy lệnh shell và trả về string kết quả, bỏ qua lỗi."""
    try:
        # startupinfo để ẩn cửa sổ command trên Windows khi build app
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


# ---------- 1. CPU ----------
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
        return platform.processor() or "Unknown CPU"

    if sysname == "Darwin":
        # Dùng đường dẫn tuyệt đối fix lỗi .app
        out = _run([MAC_CMD_SYSCTL, "-n", "machdep.cpu.brand_string"])
        if out: return out
        out = _run([MAC_CMD_SYSCTL, "-n", "hw.model"]) # Apple Silicon fallback
        return out or "Unknown CPU"

    # Linux
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "model name" in line.lower():
                    return line.split(":", 1)[1].strip()
    except:
        pass
    return "Unknown CPU"


# ---------- 2. RAM & Disk ----------
def get_ram_gb() -> float:
    try:
        return round(psutil.virtual_memory().total / (1024**3), 2)
    except:
        return 0.0

def get_disk_gb() -> float:
    """Lấy tổng dung lượng ổ đĩa hệ thống"""
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


# ---------- 3. MAC Address (Cải tiến) ----------
def get_mac_address() -> str:
    """Lấy MAC Address ưu tiên LAN hoặc Wi-Fi thực"""
    sysname = platform.system()

    # macOS: Dùng networksetup để lấy MAC phần cứng thật (ổn định nhất cho .app)
    if sysname == "Darwin":
        # Thử lấy danh sách port
        for dev in ["en0", "en1", "en2"]: # en0 thường là wifi hoặc lan chính
            out = _run([MAC_CMD_NETSETUP, "-getmacaddress", dev])
            # Output: "Ethernet Address: aa:bb:cc..."
            if "Ethernet Address:" in out:
                parts = out.split()
                if parts:
                    mac = parts[-1].strip()
                    if len(mac) >= 11: return mac.upper()

    # Windows/Linux/Fallback: Dùng psutil
    # Ưu tiên Ethernet/Wi-Fi, bỏ qua VMware/VirtualBox
    try:
        for interface, snics in psutil.net_if_addrs().items():
            if_name = interface.lower()
            # Bỏ qua interface ảo thường gặp
            if "vmware" in if_name or "virtual" in if_name or "loopback" in if_name:
                continue
            
            for snic in snics:
                if snic.family == psutil.AF_LINK:
                    mac = snic.address
                    if mac and len(mac) >= 11:
                        return mac.upper()
    except:
        pass

    return "00:00:00:00:00:00"


# ---------- 4. Hãng, Model, Năm SX (MỚI) ----------
def get_device_identity() -> dict:
    info = {"manufacturer": "Unknown", "model": "Unknown", "year": "Unknown"}
    sysname = platform.system()

    if sysname == "Windows":
        try:
            # Lấy Hãng
            v = _run(["wmic", "csproduct", "get", "vendor"]).replace("Vendor", "").strip()
            if v: info["manufacturer"] = v
            
            # Lấy Model
            m = _run(["wmic", "csproduct", "get", "name"]).replace("Name", "").strip()
            if m: info["model"] = m

            # Lấy Năm (từ BIOS Release Date: YYYYMMDD...)
            b = _run(["wmic", "bios", "get", "releasedate"]).replace("ReleaseDate", "").strip()
            if len(b) >= 4:
                info["year"] = b[:4]
        except:
            pass

    elif sysname == "Darwin":
        # Hãng
        info["manufacturer"] = "Apple Inc."
        
        # Model (VD: MacBookPro18,3)
        md = _run([MAC_CMD_SYSCTL, "-n", "hw.model"])
        if md: info["model"] = md

        # Năm SX: macOS khó lấy năm trực tiếp từ lệnh đơn giản. 
        # Ta dùng mẹo lấy thông tin tổng quan, nhưng để an toàn ta để Unknown hoặc 
        # user tự điền nếu cần. Code dưới thử lấy từ system_profiler (rất chậm) nên ta bỏ qua để app chạy nhanh.
        # Thay vào đó, Model ID (vd MacBookPro16,1) là đủ để IT tra cứu.
        
    elif sysname == "Linux":
        try:
            # Thử đọc từ DMI
            root = "/sys/devices/virtual/dmi/id"
            if os.path.exists(root):
                with open(f"{root}/sys_vendor", "r") as f: info["manufacturer"] = f.read().strip()
                with open(f"{root}/product_name", "r") as f: info["model"] = f.read().strip()
                # Năm bios
                with open(f"{root}/bios_date", "r") as f: 
                    d = f.read().strip() # MM/DD/YYYY
                    if len(d) >= 4: info["year"] = d[-4:]
        except:
            pass

    return info


# ---------- 5. VGA / GPU (MỚI) ----------
def get_gpu_info() -> str:
    sysname = platform.system()
    
    if sysname == "Windows":
        try:
            # Lấy tên card màn hình
            out = _run(["wmic", "path", "win32_VideoController", "get", "name"])
            lines = [line.strip() for line in out.splitlines() if line.strip() and "Name" not in line]
            return ", ".join(lines)
        except:
            pass

    elif sysname == "Darwin":
        try:
            # Lọc thông tin Chipset Model
            # Output mẫu: Chipset Model: Apple M1 Pro
            out = _run([MAC_CMD_PROFILER, "SPDisplaysDataType"])
            gpus = []
            for line in out.splitlines():
                if "Chipset Model:" in line:
                    gpus.append(line.split(":", 1)[1].strip())
            return ", ".join(gpus) if gpus else "Unknown VGA"
        except:
            pass

    elif sysname == "Linux":
        out = _run(["lspci"])
        gpus = []
        for line in out.splitlines():
            if "VGA" in line or "3D controller" in line:
                parts = line.split(":", 2)
                if len(parts) > 2:
                    gpus.append(parts[2].strip())
        return ", ".join(gpus) if gpus else "Unknown VGA"

    return "Unknown VGA"


# ---------- TỔNG HỢP ----------
def collect_full_info() -> dict:
    identity = get_device_identity()
    
    data = {
        "hostname": socket.gethostname(),
        "os": platform.system() + " " + platform.release(),
        "cpu": get_cpu_model(),
        "ram_gb": get_ram_gb(),
        "ssd_gb": get_disk_gb(),
        "mac_address": get_mac_address(),
        "vga": get_gpu_info(),
        "manufacturer": identity["manufacturer"],
        "model": identity["model"],
        "year": identity["year"]
    }
    return data


def format_display_text(m: dict) -> str:
    return (
        "========== THÔNG TIN THIẾT BỊ ==========\n"
        f"1. Tên máy (Hostname) : {m['hostname']}\n"
        f"2. Model              : {m['model']}\n"
        f"3. Hãng (NSX)         : {m['manufacturer']}\n"
        f"4. Năm SX (BIOS/Est)  : {m['year']}\n"
        f"5. CPU                : {m['cpu']}\n"
        f"6. RAM                : {m['ram_gb']} GB\n"
        f"7. SSD/HDD (System)   : {m['ssd_gb']} GB\n"
        f"8. VGA (GPU)          : {m['vga']}\n"
        f"9. MAC Address        : {m['mac_address']}\n"
        "=======================================\n"
    )


def send_to_server(user_name: str, data: dict) -> tuple[int, str]:
    payload = {
        "agentVersion": "3.1.0",
        "submittedAt": datetime.now(timezone.utc).isoformat(),
        "userInputName": user_name,
        "machine": data
    }
    # Mapping lại key cho đúng với Database server nếu cần
    # Ví dụ server cần key 'ssd_total_gb' thay vì 'ssd_gb' thì sửa ở đây hoặc đổi ở hàm collect
    
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
    
    # Center window
    w, h = 600, 500
    ws, hs = root.winfo_screenwidth(), root.winfo_screenheight()
    x, y = (ws/2) - (w/2), (hs/2) - (h/2)
    root.geometry(f'{w}x{h}+{int(x)}+{int(y)}')

    # UI Components
    lbl_frame = tk.Frame(root)
    lbl_frame.pack(fill="x", padx=10, pady=10)
    
    tk.Label(lbl_frame, text="Nhập Tên / Mã Nhân Viên:", font=("Arial", 10, "bold")).pack(side="left")
    
    name_var = tk.StringVar()
    entry_name = tk.Entry(lbl_frame, textvariable=name_var, font=("Arial", 11))
    entry_name.pack(side="left", fill="x", expand=True, padx=(10, 0))
    entry_name.focus()

    txt_info = scrolledtext.ScrolledText(root, font=("Consolas", 10), height=15)
    txt_info.pack(fill="both", expand=True, padx=10, pady=5)

    # Logic
    def load_data():
        txt_info.delete("1.0", tk.END)
        txt_info.insert(tk.END, "Đang quét phần cứng... vui lòng chờ...\n")
        root.update()
        
        data = collect_full_info()
        root._scanned_data = data # Lưu tạm vào biến global của window
        
        display_str = format_display_text(data)
        txt_info.delete("1.0", tk.END)
        txt_info.insert(tk.END, display_str)

    def on_send():
        name = name_var.get().strip()
        if not name:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập tên hoặc mã nhân viên trước khi gửi.")
            entry_name.focus()
            return
            
        if not hasattr(root, "_scanned_data"):
            load_data()
            
        data = getattr(root, "_scanned_data")
        
        # Gửi
        code, resp = send_to_server(name, data)
        if code == 200:
            messagebox.showinfo("Thành công", "✅ Đã gửi thông tin thiết bị về hệ thống thành công!")
        else:
            messagebox.showerror("Thất bại", f"Gửi lỗi (Code {code}):\n{resp}")

    # Buttons
    btn_frame = tk.Frame(root, pady=10)
    btn_frame.pack(fill="x")

    btn_scan = tk.Button(btn_frame, text="🔄 Quét Lại", command=load_data, height=2, width=15)
    btn_scan.pack(side="left", padx=20)
    
    btn_send = tk.Button(btn_frame, text="📤 Gửi Báo Cáo", command=on_send, height=2, width=15, bg="#4CAF50", fg="white")
    btn_send.pack(side="right", padx=20)

    # Auto load lần đầu
    root.after(500, load_data)
    
    root.mainloop()

if __name__ == "__main__":
    run_app()