import customtkinter as ctk
import tkinter as tk
import threading, time, requests, concurrent.futures, subprocess, os, sys, json, socket, base64
from PIL import Image, ImageDraw, ImageFont, ImageTk
try:
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    import winreg
    WINDOWS = True
except ImportError:
    WINDOWS = False

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ── Colors ─────────────────────────────────────────────────────────────────────
BG      = "#f4f6f9"
CARD    = "#ffffff"
CARD2   = "#f0f2f5"
BORDER  = "#dde1e7"
ACCENT  = "#1a6bff"
ACCENT2 = "#0052cc"
GREEN   = "#1a8a3c"
RED     = "#d93025"
ORANGE  = "#e37400"
TEXT    = "#1a1f2e"
MUTED   = "#5f6b7a"
DIMMED  = "#8c96a3"
TIMEOUT = 10
LOCAL_PORT = 8877

# ── Asset path ────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BUNDLE_DIR = sys._MEIPASS          # bundled assets (read-only)
    EXE_DIR    = os.path.dirname(sys.executable)  # next to .exe (writable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR    = BUNDLE_DIR

def asset(name):
    """Read-only bundled assets (icons, images)."""
    return os.path.join(BUNDLE_DIR, name)

def exe_asset(name):
    """Writable files saved next to the .exe."""
    return os.path.join(EXE_DIR, name)

DEFAULT_API_KEY = "x0sqbnhconr4qezdtna7qubewvy94zbr343vy6qw"
REG_PATH = r"Software\JayVPN"

# Map country code -> local PNG filename (files sit next to main.py)
FLAG_PNG = {
    "US": "usa.png",
    "GB": "uk.png",
    "DE": "ger.png",
    "JP": "jp.png",
}

COUNTRY_NAMES = {
    "US":"United States","GB":"United Kingdom","DE":"Germany","FR":"France",
    "JP":"Japan","CA":"Canada","NL":"Netherlands","SG":"Singapore","BR":"Brazil",
    "AU":"Australia","IN":"India","KR":"South Korea","PL":"Poland","CH":"Switzerland",
    "RU":"Russia","IT":"Italy","ES":"Spain","SE":"Sweden","NO":"Norway","HK":"Hong Kong",
    "TW":"Taiwan","TH":"Thailand","VN":"Vietnam","ID":"Indonesia","TR":"Turkey",
    "MX":"Mexico","AR":"Argentina","ZA":"South Africa","UA":"Ukraine","PH":"Philippines",
}

# ── Flag image loader ──────────────────────────────────────────────────────────
_flag_cache = {}   # cc -> ctk.CTkImage

def get_flag_ctk(cc, size=(28, 19)):
    if cc in _flag_cache:
        return _flag_cache[cc]
    fname = FLAG_PNG.get(cc)
    if not fname:
        return None
    path = asset(fname)
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
        ctk_img = ctk.CTkImage(img, size=size)
        _flag_cache[cc] = ctk_img
        return ctk_img
    except:
        return None

def load_settings():
    """Load settings from Windows Registry (falls back to defaults)."""
    result = {"api_key": DEFAULT_API_KEY}
    if WINDOWS:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
            try:
                val, _ = winreg.QueryValueEx(k, "api_key")
                if val: result["api_key"] = val
            except: pass
            winreg.CloseKey(k)
        except: pass
    return result

def save_settings(d):
    """Save settings to Windows Registry — no external files."""
    if WINDOWS:
        try:
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH)
            for key, val in d.items():
                winreg.SetValueEx(k, key, 0, winreg.REG_SZ, str(val))
            winreg.CloseKey(k)
        except: pass
    # Non-Windows fallback only
    else:
        import json as _json
        try:
            with open(exe_asset("jayvpn_settings.json"), "w") as f:
                _json.dump(d, f)
        except: pass

def get_api_key():
    # One-time migration: import key from old JSON file if registry is still empty
    if WINDOWS:
        try:
            import json as _json, os as _os
            old_file = exe_asset("jayvpn_settings.json")
            reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
            winreg.CloseKey(reg_key)
        except:
            # Registry key doesn't exist yet — try to migrate from JSON
            try:
                with open(exe_asset("jayvpn_settings.json")) as f:
                    data = _json.load(f)
                if data.get("api_key"):
                    save_settings(data)
                    _os.remove(exe_asset("jayvpn_settings.json"))
            except: pass
    key = load_settings().get("api_key", DEFAULT_API_KEY)
    return key if key and len(key) > 10 else DEFAULT_API_KEY

# ── Local relay ────────────────────────────────────────────────────────────────
_relay_server = None

def start_relay(proxy):
    global _relay_server
    stop_relay()
    host  = proxy["ip"]
    port  = int(proxy["port"])
    creds = base64.b64encode(f"{proxy['user']}:{proxy['pass']}".encode()).decode()
    auth  = f"Proxy-Authorization: Basic {creds}\r\n".encode()

    def handle(client):
        try:
            buf = b""
            while b"\r\n\r\n" not in buf:
                c = client.recv(4096)
                if not c: return
                buf += c
            end = buf.find(b"\r\n\r\n")
            hdrs = buf[:end]; body = buf[end:]
            first = hdrs.find(b"\r\n")
            new_hdrs = hdrs[:first+2] + auth + hdrs[first+2:]
            up = socket.create_connection((host, port), timeout=TIMEOUT)
            up.sendall(new_hdrs + body)
            def relay(s, d):
                try:
                    while True:
                        x = s.recv(8192)
                        if not x: break
                        d.sendall(x)
                except: pass
                finally:
                    for sock in (s,d):
                        try: sock.shutdown(socket.SHUT_WR)
                        except: pass
            t1=threading.Thread(target=relay,args=(client,up),daemon=True)
            t2=threading.Thread(target=relay,args=(up,client),daemon=True)
            t1.start(); t2.start(); t1.join(); t2.join()
        except: pass
        finally:
            try: client.close()
            except: pass

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", LOCAL_PORT))
    srv.listen(100)
    _relay_server = srv
    def loop():
        while True:
            try:
                c,_ = srv.accept()
                threading.Thread(target=handle,args=(c,),daemon=True).start()
            except: break
    threading.Thread(target=loop,daemon=True).start()

def stop_relay():
    global _relay_server
    if _relay_server:
        try: _relay_server.close()
        except: pass
        _relay_server = None

# ── System proxy ───────────────────────────────────────────────────────────────
def set_sys_proxy():
    if not WINDOWS: return
    try:
        a = f"127.0.0.1:{LOCAL_PORT}"
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k,"ProxyEnable",  0,winreg.REG_DWORD,1)
        winreg.SetValueEx(k,"ProxyServer",  0,winreg.REG_SZ,f"http={a};https={a};ftp={a}")
        winreg.SetValueEx(k,"ProxyOverride",0,winreg.REG_SZ,"localhost;127.*;10.*;192.168.*")
        winreg.CloseKey(k)
        _refresh()
    except: pass

def clear_sys_proxy():
    if not WINDOWS: return
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k,"ProxyEnable",0,winreg.REG_DWORD,0)
        winreg.SetValueEx(k,"ProxyServer", 0,winreg.REG_SZ,"")
        winreg.CloseKey(k)
        _refresh()
    except: pass

def _refresh():
    try:
        import ctypes; w=ctypes.WinDLL("wininet.dll")
        w.InternetSetOptionW(0,39,0,0); w.InternetSetOptionW(0,37,0,0)
    except: pass

# ── Network helpers ────────────────────────────────────────────────────────────
def get_ip(via=None):
    px = None
    if via:
        a = f"http://{via['user']}:{via['pass']}@{via['ip']}:{via['port']}"
        px = {"http":a,"https":a}
    for url in ["https://api.ipify.org?format=json","https://api4.my-ip.io/ip.json"]:
        try: return requests.get(url,timeout=TIMEOUT,proxies=px).json().get("ip","?")
        except: pass
    return "Unavailable"

def fetch_available_countries(api_key):
    try:
        r = requests.get(
            "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100",
            headers={"Authorization":f"Token {api_key}"}, timeout=10)
        if r.status_code == 200:
            codes = set()
            for p in r.json().get("results",[]):
                codes.add(p.get("country_code","").upper())
            options = []
            for cc in sorted(codes):
                name = COUNTRY_NAMES.get(cc, cc)
                options.append((name, cc))
            return options
    except: pass
    return [("United States","US"),("United Kingdom","GB"),
            ("Germany","DE"),("Japan","JP")]

def fetch_proxies(api_key, cc=None):
    proxies=[]
    try:
        url="https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
        if cc: url+=f"&country_code__in={cc}"
        r=requests.get(url,headers={"Authorization":f"Token {api_key}"},timeout=10)
        if r.status_code==200:
            for p in r.json().get("results",[]):
                proxies.append({"ip":p["proxy_address"],"port":str(p["port"]),
                    "user":p["username"],"pass":p["password"],"type":"http"})
    except: pass
    return proxies

def test_proxy(proxy):
    """Accept proxy if the TCP port is reachable — real validation happens via get_ip."""
    try:
        s = socket.create_connection((proxy["ip"], int(proxy["port"])), timeout=5)
        s.close()
        return True
    except:
        return False

def find_best(proxies, log_cb=None):
    result=[None]; lock=threading.Lock(); n=[0]
    def test(p):
        with lock:
            if result[0]: return
        with lock: n[0]+=1; i=n[0]
        if log_cb: log_cb(f"Testing {i}/{len(proxies)}: {p['ip']}:{p['port']}")
        if test_proxy(p):
            with lock:
                if not result[0]:
                    result[0]=p
                    if log_cb: log_cb(f"✓ Working: {p['ip']}:{p['port']}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futs=[ex.submit(test,p) for p in proxies]
        for f in concurrent.futures.as_completed(futs):
            with lock:
                if result[0]: break
    return result[0]

def ping_proxy(proxy):
    try:
        a=f"http://{proxy['user']}:{proxy['pass']}@{proxy['ip']}:{proxy['port']}"
        t0=time.time()
        requests.get("https://www.google.com",proxies={"http":a,"https":a},timeout=TIMEOUT)
        return int((time.time()-t0)*1000)
    except: return None

def launch_chrome():
    addr = f"http://127.0.0.1:{LOCAL_PORT}"
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]:
        if os.path.exists(p):
            subprocess.Popen([p,f"--proxy-server={addr}",
                "--proxy-bypass-list=<-loopback>","--new-window","https://www.google.com"])
            return True
    return False


# ── Custom Country Dropdown ────────────────────────────────────────────────────
class CountryDropdown(ctk.CTkFrame):
    """A polished custom dropdown with flag images and hover effects."""

    def __init__(self, parent, values=None, variable=None, command=None, **kwargs):
        super().__init__(parent, fg_color="#ffffff", corner_radius=12,
            border_width=1, border_color="#dde1e7", height=52)
        self.pack_propagate(False)

        self._values   = values or []
        self._variable = variable or ctk.StringVar(value="")
        self._command  = command
        self._open     = False
        self._popup    = None
        self._flag_cache = {}

        # ── Trigger row ────────────────────────────────────────────────────
        self._trigger = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        self._trigger.pack(fill="both", expand=True, padx=10, pady=8)

        self._flag_lbl = ctk.CTkLabel(self._trigger, text="",
            fg_color="transparent", corner_radius=6, width=32, height=32)
        self._flag_lbl.pack(side="left", padx=(0, 8))

        self._text_lbl = ctk.CTkLabel(self._trigger,
            text=self._variable.get(),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#1a1f2e", anchor="w")
        self._text_lbl.pack(side="left", fill="x", expand=True)



        # Bind clicks on all children
        for w in [self, self._trigger, self._flag_lbl, self._text_lbl]:
            w.bind("<Button-1>", self._toggle)
            w.bind("<Enter>", lambda e: self.configure(fg_color="#f8f9fb"))
            w.bind("<Leave>", lambda e: self.configure(fg_color="#ffffff"))

    def configure(self, **kw):
        if "values" in kw:
            self._values = kw.pop("values")
        if "variable" in kw:
            self._variable = kw.pop("variable")
        super().configure(**kw)

    def _get_flag(self, label):
        if label in self._flag_cache:
            return self._flag_cache[label]
        # Look up cc from label text
        for cc, fname in FLAG_PNG.items():
            name = COUNTRY_NAMES.get(cc, cc)
            if name in label or label in name:
                path = asset(fname)
                if os.path.exists(path):
                    try:
                        raw = Image.open(path).convert("RGBA")
                        img = ctk.CTkImage(raw, size=(28, 19))
                        self._flag_cache[label] = img
                        return img
                    except: pass
        return None

    def set(self, value):
        self._variable.set(value)
        self._text_lbl.configure(text=value)
        img = self._get_flag(value)
        if img:
            self._flag_lbl.configure(image=img, text="")
        else:
            self._flag_lbl.configure(image=None, text="")

    def get(self):
        return self._variable.get()

    def _toggle(self, event=None):
        if self._open:
            self._close()
        else:
            self._show()

    def _show(self):
        if self._popup and self._popup.winfo_exists():
            return
        self._open = True
        

        # Calculate position below the trigger
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        w = self.winfo_width()

        self._popup = tk.Toplevel(self)
        self._popup.overrideredirect(True)
        self._popup.configure(bg="#ffffff")
        self._popup.geometry(f"{w}x{min(len(self._values)*46+8, 240)}+{x}+{y}")
        self._popup.lift()
        self._popup.focus_set()
        self._popup.bind("<Escape>", lambda e: self._close())

        # Close when clicking anywhere outside the popup
        def _on_click_outside(e):
            try:
                wx, wy = self._popup.winfo_rootx(), self._popup.winfo_rooty()
                ww, wh = self._popup.winfo_width(), self._popup.winfo_height()
                if not (wx <= e.x_root <= wx+ww and wy <= e.y_root <= wy+wh):
                    self._close()
            except: self._close()

        self._popup.bind_all("<Button-1>", _on_click_outside)

        # Outer frame with border + shadow feel
        outer = tk.Frame(self._popup, bg="#a0a8b4", bd=0, relief="flat")
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        inner_wrap = tk.Frame(outer, bg="#ffffff", bd=0)
        inner_wrap.pack(fill="both", expand=True, padx=0, pady=0)

        canvas = tk.Canvas(inner_wrap, bg="#ffffff", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        scroll = tk.Scrollbar(inner_wrap, orient="vertical", command=canvas.yview,
            width=8, troughcolor="#f0f2f5", bg="#c0c8d0")
        if len(self._values) > 5:
            scroll.pack(side="right", fill="y")
            canvas.configure(yscrollcommand=scroll.set)

        frame = tk.Frame(canvas, bg="#ffffff")
        frame_id = canvas.create_window((0,0), window=frame, anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(frame_id, width=e.width)
        frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        current = self._variable.get()

        for val in self._values:
            is_selected = (val == current)
            row_bg  = "#e8f0fe" if is_selected else "#ffffff"
            row_fg  = "#1a6bff" if is_selected else "#1a1f2e"

            row = tk.Frame(frame, bg=row_bg, cursor="hand2", height=44)
            row.pack(fill="x", padx=0, pady=0)
            row.pack_propagate(False)
            # Bottom separator
            tk.Frame(frame, bg="#e8eaed", height=1).pack(fill="x")

            # Country name only - no flag icon in list
            lbl_name = tk.Label(row, text=val, bg=row_bg, fg=row_fg,
                font=("Segoe UI", 11, "bold" if is_selected else "normal"),
                anchor="w", bd=0, highlightthickness=0, padx=14)
            lbl_name.pack(side="left", fill="x", expand=True)



            def _on_hover(e, r=row, n=lbl_name, s=is_selected):
                if not s:
                    r.configure(bg="#f4f6f9")
                    n.configure(bg="#f4f6f9")
            def _on_leave(e, r=row, n=lbl_name, bg=row_bg, s=is_selected):
                if not s:
                    r.configure(bg=bg)
                    n.configure(bg=bg)
            def _on_click(e, v=val):
                self.set(v)
                self._close()
                if self._command: self._command(v)

            for w in [row, lbl_name]:
                w.bind("<Enter>",    _on_hover)
                w.bind("<Leave>",    _on_leave)
                w.bind("<Button-1>", _on_click)

    def _close(self):
        self._open = False
        
        if self._popup:
            try:
                self._popup.unbind_all("<Button-1>")
                self._popup.destroy()
            except: pass
            self._popup = None

# ── Settings Window ────────────────────────────────────────────────────────────
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        self.title("Settings")
        self.geometry("440x290"); self.resizable(False, False)
        self.configure(fg_color="#f4f6f9"); self.grab_set()
        def _apply_icon():
            try:
                for name in ("256x256.ico", "icon.ico"):
                    p = asset(name)
                    if os.path.exists(p): self.wm_iconbitmap(p); break
            except: pass
        self.after(250, _apply_icon)

        ctk.CTkLabel(self, text="API Key", font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT).pack(pady=(24, 4), padx=24, anchor="w")

        # Entry + Clear button on same row
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(12, 0))

        self.entry = ctk.CTkEntry(row, height=44, font=ctk.CTkFont(size=12),
            fg_color=CARD2, border_color=BORDER, text_color=TEXT,
            placeholder_text="Paste your new API token here…")
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(row, text="Clear", width=68, height=44,
            fg_color=CARD2, hover_color=BORDER, text_color=MUTED,
            font=ctk.CTkFont(size=12), corner_radius=10, border_width=1,
            border_color=BORDER, command=self._clear).pack(side="left")

        s = load_settings()
        if s.get("api_key"): self.entry.insert(0, s["api_key"])

        # Select-all on focus so user can immediately replace the key
        self.entry.bind("<FocusIn>", lambda e: self.entry.select_range(0, "end"))

        self.status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color=MUTED)
        self.status.pack(pady=(10, 0))

        ctk.CTkButton(self, text="Test & Save", height=44, fg_color=ACCENT,
            hover_color="#1a5cc4", text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"), corner_radius=10,
            command=self._save).pack(fill="x", padx=24, pady=(14, 0))

    def _clear(self):
        self.entry.delete(0, "end")
        self.entry.focus_set()
        self.status.configure(text="")

    def _save(self):
        key = self.entry.get().strip()
        if not key:
            self.status.configure(text="Please enter a key", text_color=RED); return
        self.status.configure(text="Validating…", text_color=ORANGE); self.update()
        def go():
            save_settings({"api_key": key})
            self._parent._log("✓ Windows Registry updated with new API key")
            try:
                r = requests.get("https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=1",
                    headers={"Authorization": f"Token {key}"}, timeout=10)
                if r.status_code == 200:
                    cnt = r.json().get("count", 0)
                    self.status.configure(
                        text=f"✅  API Verified — {cnt} proxies available", text_color=GREEN)
                    self._parent._log(f"✓ API verified — {cnt} proxies available, ready to connect")
                    threading.Thread(target=self._parent._load_countries, daemon=True).start()
                else:
                    self.status.configure(
                        text=f"❌  Incorrect API Key (HTTP {r.status_code})", text_color=RED)
                    self._parent._log(f"✗ Incorrect API Key — please update it in ⚙ Settings")
            except Exception as e:
                self.status.configure(text=f"❌  Incorrect API Key — could not reach server", text_color=RED)
                self._parent._log("✗ Incorrect API Key — could not reach server")
        threading.Thread(target=go, daemon=True).start()

# ── Main App ───────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.connected=self.connecting=False
        self.proxy=None
        self.country_map={}   # label -> cc

        self.logo_img   = None
        self.chrome_img = None
        self.flag_img   = None

        self.title("JayVPN")
        self.geometry("420x700")
        self.minsize(380, 620)
        self.configure(fg_color=BG)
        self.update_idletasks()
        self.geometry(f"420x700+{(self.winfo_screenwidth()-420)//2}+{(self.winfo_screenheight()-700)//2}")

        try:
            icon_path = asset("256x256.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except: pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Unmap>", self._on_minimize)
        self._tray_icon = None
        self._build_ui()
        threading.Thread(target=self._init_data, daemon=True).start()
        if HAS_TRAY:
            threading.Thread(target=self._setup_tray, daemon=True).start()

    def _init_data(self):
        ip = get_ip()
        self.lbl_real.configure(text=ip)
        self._load_countries()

    def _load_countries(self):
        api_key = get_api_key()
        options = fetch_available_countries(api_key)
        self.country_map = {label: cc for label, cc in options}
        labels = [label for label, _ in options]
        self.country_menu.configure(values=labels)
        if labels:
            self.country_menu.set(labels[0])
            first_cc = options[0][1]
            self.after(0, lambda: self._update_flag(first_cc))
        self._log(f"Loaded {len(labels)} available countries")

    def _update_flag(self, cc):
        pass  # flag is now handled inside CountryDropdown

    def _on_country_change(self, label):
        cc = self.country_map.get(label, "")
        self._update_flag(cc)
        self.country_menu.set(label)

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=64, border_width=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        logo_path = asset("logo.png")
        if os.path.exists(logo_path):
            try:
                self.logo_img = ctk.CTkImage(Image.open(logo_path), size=(50,50))
                ctk.CTkLabel(hdr, image=self.logo_img, text="").place(x=14, rely=0.5, anchor="w")
            except:
                self._j_badge(hdr)
        else:
            self._j_badge(hdr)

        ctk.CTkLabel(hdr, text="JayVPN",
            font=ctk.CTkFont(size=22, weight="bold"), text_color="#1a1f2e"
            ).place(x=64, rely=0.5, anchor="w")

        # Status image badge (online.png / offline.png)
        self._pulse_running = False
        self._pulse_state   = True

        def _load_status_img(name, fallback_w=100, fallback_h=36):
            path = asset(name)
            if os.path.exists(path):
                try:
                    raw = Image.open(path).convert("RGBA")
                    # Auto-size: keep aspect ratio, height=36
                    w, h = raw.size
                    new_w = int(w * 36 / h)
                    return ctk.CTkImage(raw, size=(new_w, 36))
                except: pass
            return None

        self._img_offline = _load_status_img("offline.png")
        self._img_online  = _load_status_img("online.png")

        self.status_lbl = ctk.CTkLabel(hdr,
            image=self._img_offline if self._img_offline else None,
            text="" if self._img_offline else "Offline",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#c0392b", fg_color="transparent")
        self.status_lbl.place(relx=1, x=-56, rely=0.5, anchor="e")

        # Settings PNG icon button
        try:
            _simg = ctk.CTkImage(Image.open(asset("settings.png")), size=(24,24))
        except:
            _simg = None
        ctk.CTkButton(hdr, image=_simg, text="" if _simg else "⚙",
            width=36, height=36, fg_color="transparent",
            hover_color=CARD2, corner_radius=8,
            font=ctk.CTkFont(size=17), text_color=MUTED,
            command=lambda: SettingsWindow(self)
            ).place(relx=1, x=-12, rely=0.5, anchor="e")

        ctk.CTkFrame(self, fg_color="#dde1e7", height=1, corner_radius=0).pack(fill="x")

        # ── Body ────────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(body, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14, pady=12)

        ip_row = ctk.CTkFrame(inner, fg_color="transparent")
        ip_row.pack(fill="x", pady=(0,10))
        ip_row.columnconfigure((0,1), weight=1)
        self._ip_card(ip_row, "Your IP",   "lbl_real", 0)
        self._ip_card(ip_row, "Masked IP", "lbl_mask", 1)

        conn_card = ctk.CTkFrame(inner, fg_color=CARD, corner_radius=16,
            border_width=1, border_color=BORDER)
        conn_card.pack(fill="x", pady=(0,10))

        self.btn = ctk.CTkButton(conn_card,
            text="⏻   CONNECT",
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#1db954", hover_color="#17a34a",
            text_color="white", corner_radius=12, height=48,
            command=self._toggle)
        self.btn.pack(padx=14, pady=(14,8), fill="x")

        self.detail = ctk.CTkLabel(conn_card,
            text="Choose a server location and connect",
            font=ctk.CTkFont(size=12), text_color=MUTED)
        self.detail.pack(pady=(0,12))

        chrome_frame = ctk.CTkFrame(inner, fg_color=CARD, corner_radius=12,
            border_width=1, border_color=BORDER)
        chrome_frame.pack(fill="x", pady=(0,10))

        chrome_path = asset("chrome.png")
        if os.path.exists(chrome_path):
            try:
                self.chrome_img = ctk.CTkImage(Image.open(chrome_path), size=(22,22))
            except: pass

        self.chrome_btn = ctk.CTkButton(chrome_frame,
            text="  Open Chrome",
            image=self.chrome_img, compound="left",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="transparent", hover_color=CARD2,
            text_color=MUTED, corner_radius=10, height=38,
            border_width=0, command=self._open_chrome, state="disabled")
        self.chrome_btn.pack(padx=4, pady=4, fill="x")

        # ── Server location ──────────────────────────────────────────────
        ctk.CTkLabel(inner, text="SERVER LOCATION",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=DIMMED).pack(anchor="w", pady=(0,6))

        self.cvar = ctk.StringVar(value="Loading…")
        self.country_menu = CountryDropdown(inner,
            values=["Loading…"],
            variable=self.cvar,
            command=self._on_country_change)
        self.country_menu.pack(fill="x", pady=(0,10))

        # Stats row
        stats = ctk.CTkFrame(inner, fg_color="transparent")
        stats.pack(fill="x", pady=(0,10))
        stats.columnconfigure((0,1,2), weight=1)
        self._stat(stats, "Ping",     "lbl_ping",  "—",    0)
        self._stat(stats, "Relay",    "lbl_relay", "OFF",  1)
        self._stat(stats, "Protocol", "lbl_proto", "HTTP", 2)

        ctk.CTkLabel(inner, text="ACTIVITY LOG",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=DIMMED).pack(anchor="w", pady=(0,6))

        self.log = ctk.CTkTextbox(inner, height=110, fg_color="#0d0d0d",
            border_color="#000000", border_width=1,
            font=ctk.CTkFont(family="Courier New", size=11),
            text_color="#e0e0e0", corner_radius=10, state="disabled",
            wrap="word")
        self.log.pack(fill="x", pady=(0,6))
        # Configure color tags for the underlying tk Text widget
        self.log._textbox.tag_configure("green", foreground="#00e676")
        self.log._textbox.tag_configure("red",   foreground="#ff5252")
        self.log._textbox.tag_configure("white", foreground="#e0e0e0")

        ctk.CTkLabel(inner,
            text="JayVPN  ·  version 1.0",
            font=ctk.CTkFont(size=10), text_color=DIMMED).pack(pady=(4,0))

    def _j_badge(self, parent):
        f = ctk.CTkFrame(parent, fg_color=ACCENT, corner_radius=10, width=40, height=40)
        f.place(x=14, rely=0.5, anchor="w"); f.pack_propagate(False)
        ctk.CTkLabel(f, text="J", font=ctk.CTkFont(size=22, weight="bold"),
            text_color="white").place(relx=0.5, rely=0.5, anchor="center")

    def _ip_card(self, parent, title, attr, col):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
            border_width=1, border_color=BORDER)
        c.grid(row=0, column=col, padx=(0, 8 if col==0 else 0), sticky="nsew")
        ctk.CTkLabel(c, text=title,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=DIMMED).pack(anchor="w", padx=12, pady=(8,1))
        lbl = ctk.CTkLabel(c, text="...",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=ACCENT2)
        lbl.pack(anchor="w", padx=12, pady=(0,8))
        setattr(self, attr, lbl)

    def _stat(self, parent, title, attr, val, col):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
            border_width=1, border_color=BORDER)
        c.grid(row=0, column=col, padx=(0, 8 if col<2 else 0), sticky="nsew")
        ctk.CTkLabel(c, text=title,
            font=ctk.CTkFont(size=10), text_color=DIMMED).pack(pady=(7,1))
        lbl = ctk.CTkLabel(c, text=val,
            font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT)
        lbl.pack(pady=(0,7))
        setattr(self, attr, lbl)

    def _log(self, msg):
        self.log.configure(state="normal")
        ts = f"[{time.strftime('%H:%M:%S')}] "
        line = ts + msg + "\n"
        # Determine color tag based on message content
        low = msg.lower()
        if any(k in low for k in ["✓", "connected", "working", "verified", "saved", "loaded", "protected", "open chrome", "ready to connect", "browse"]):
            tag = "green"
        elif any(k in low for k in ["✗", "failed", "error", "invalid", "disconnected", "incorrect", "unavailable", "no proxies", "check your"]):
            tag = "red"
        else:
            tag = "white"
        start = self.log._textbox.index("end-1c")
        self.log.insert("end", line)
        end = self.log._textbox.index("end-1c")
        self.log._textbox.tag_add(tag, start, end)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, state):
        """state: 'Online', 'Offline', 'Connecting'"""
        self._stop_pulse()
        if state == "Online":
            img  = self._img_online
            text = "" if img else "Online"
            self.status_lbl.configure(image=img, text=text, text_color="#1a8a3c")
        elif state == "Connecting":
            # Pulse between online and offline images
            self._start_pulse()
        else:
            img  = self._img_offline
            text = "" if img else "Offline"
            self.status_lbl.configure(image=img, text=text, text_color="#c0392b")

    def _start_pulse(self):
        self._pulse_running = True
        self._pulse_state   = True
        def pulse():
            while self._pulse_running:
                img  = self._img_online if self._pulse_state else self._img_offline
                text = "" if img else ("Online" if self._pulse_state else "Offline")
                try:
                    self.status_lbl.configure(image=img, text=text)
                except: break
                self._pulse_state = not self._pulse_state
                time.sleep(0.5)
        threading.Thread(target=pulse, daemon=True).start()

    def _stop_pulse(self):
        self._pulse_running = False

    def _dot(self, color):
        pass  # no longer used — kept for compatibility

    def _toggle(self):
        if self.connecting: return
        if self.connected: self._disconnect()
        else: threading.Thread(target=self._connect, daemon=True).start()

    def _open_chrome(self):
        ok = launch_chrome()
        self._log("✓ Chrome opened → google.com" if ok else "✗ Chrome not found on this PC")

    def _connect(self):
        self.connecting = True
        label   = self.cvar.get()
        code    = self.country_map.get(label)
        api_key = get_api_key()

        self.btn.configure(text="⟳   CONNECTING…", fg_color=ORANGE,
            hover_color=ORANGE, state="disabled")
        self._set_status("Connecting")
        self.detail.configure(text=f"Fetching proxies for {label}…")
        self._log(f"Connecting to {label}…")

        proxies = fetch_proxies(api_key, code)
        if not proxies:
            self._log("No proxies for that country — trying all available…")
            proxies = fetch_proxies(api_key, None)

        if not proxies:
            self._log("✗ No proxies found — check API key in ⚙")
            self._reset(); return

        self._log(f"Found {len(proxies)} proxies — testing…")
        # find_best does TCP test; then verify each candidate actually routes traffic
        p = None
        candidates = list(proxies)
        # Also include proxies from all countries as fallback
        all_proxies = fetch_proxies(api_key, None)
        extra = [px for px in all_proxies if px["ip"] not in {c["ip"] for c in candidates}]
        candidates += extra

        self._log(f"Testing {len(candidates)} proxies (TCP + routing)…")
        for candidate in candidates:
            try:
                s = socket.create_connection((candidate["ip"], int(candidate["port"])), timeout=5)
                s.close()
            except:
                continue
            # Quick routing check via the relay
            self._log(f"Trying {candidate['ip']}:{candidate['port']}…")
            try:
                a = f"http://{candidate['user']}:{candidate['pass']}@{candidate['ip']}:{candidate['port']}"
                r = requests.get("http://ip-api.com/json", proxies={"http": a, "https": a}, timeout=8)
                if r.status_code < 400:
                    p = candidate
                    self._log(f"✓ Working: {candidate['ip']}:{candidate['port']}")
                    break
            except:
                continue

        if not p:
            self._log("✗ All proxies failed — check your API key in ⚙")
            self._reset(); return

        start_relay(p)
        set_sys_proxy()

        self.proxy = p
        masked = get_ip(via=p)
        ms     = ping_proxy(p)

        self.connected  = True
        self.connecting = False

        self.btn.configure(text="⏹   DISCONNECT", fg_color=RED,
            hover_color="#c0392b", state="normal")
        self._set_status("Online")
        self.lbl_mask.configure(text=masked or p["ip"])
        self.lbl_ping.configure(text=f"{ms} ms" if ms else "—")
        self.lbl_relay.configure(text="ON", text_color=GREEN)
        self.detail.configure(text=f"Protected via {label} · {p['ip']}")
        self.chrome_btn.configure(state="normal", text_color=ACCENT2)
        self._log(f"✓ Connected!  IP: {masked}  Ping: {ms}ms")
        self._log("Click 'Open Chrome' to browse with JayVPN")

    def _disconnect(self):
        stop_relay()
        clear_sys_proxy()
        self.connected = self.connecting = False
        self.proxy = None
        self._reset()
        self._log("Disconnected — your real IP is restored")
        threading.Thread(target=lambda: self.lbl_real.configure(text=get_ip()),
            daemon=True).start()

    def _reset(self):
        self.connecting = False
        self.btn.configure(text="⏻   CONNECT", fg_color="#1db954",
            hover_color="#17a34a", text_color="white", state="normal")
        self._set_status("Offline")
        self.lbl_mask.configure(text="—")
        self.lbl_ping.configure(text="—")
        self.lbl_relay.configure(text="OFF", text_color=TEXT)
        self.detail.configure(text="Choose a server location and connect")
        self.chrome_btn.configure(state="disabled", text_color=MUTED)

    def _on_minimize(self, event):
        if event.widget is self and HAS_TRAY:
            self.after(50, self._hide_to_tray)

    def _hide_to_tray(self):
        self.withdraw()

    def _show_from_tray(self, icon=None, item=None):
        self.after(0, self._do_show)

    def _do_show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_from_tray(self, icon=None, item=None):
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self._on_close)

    def _setup_tray(self):
        # Build a simple icon image
        try:
            ico_path = asset("256x256.ico")
            if os.path.exists(ico_path):
                img = Image.open(ico_path).convert("RGBA").resize((64, 64))
            else:
                raise FileNotFoundError
        except:
            img = Image.new("RGBA", (64, 64), (26, 107, 255, 255))
            d = ImageDraw.Draw(img)
            d.text((20, 16), "J", fill="white")

        menu = pystray.Menu(
            pystray.MenuItem("Show JayVPN", self._show_from_tray, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit_from_tray),
        )
        self._tray_icon = pystray.Icon("JayVPN", img, "JayVPN", menu)
        self._tray_icon.run()

    def _on_close(self):
        if self._tray_icon:
            self._tray_icon.stop()
        stop_relay()
        clear_sys_proxy()
        self.destroy()

if __name__ == "__main__":
    # ── Single instance lock ───────────────────────────────────────────────
    _mutex = None
    if WINDOWS:
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "JayVPN_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            import tkinter as _tk, tkinter.messagebox as _mb
            _r = _tk.Tk(); _r.withdraw()
            _mb.showwarning("JayVPN", "JayVPN is already active.")
            _r.destroy()
            raise SystemExit
    App().mainloop()