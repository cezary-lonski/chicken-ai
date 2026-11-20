import os
import sys
import json
import time
import queue
import threading
import subprocess
import tempfile
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

APP_NAME = "Chicken AI"
VERSION = "0.1.0"
CHANNEL = "beta"
GITHUB_REPO = "cezary-lonski/chicken-ai"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-flash-latest"

DEFAULT_PROMPT = (
    "Jesteś Chicken AI, przyjazny asystent w formie kurczaka. "
    "Zawsze przedstawiaj się jako Chicken AI. "
    "Odpowiadaj po polsku (chyba że użytkownik pisze w innym języku), konkretnie i pomocnie. "
    "Czasem możesz dodać żartobliwe 'kokoko', ale nie przesadzaj."
)
AGENT_PROMPT = (
    "\n\nTRYB AGENTA: masz do dyspozycji narzędzia do pracy na plikach i komendach w folderze roboczym "
    "użytkownika. Działaj krok po kroku: najpierw zbadaj (list_dir, read_file), potem wprowadzaj zmiany "
    "(write_file, run_command). Zapis plików i komendy wymagają zgody użytkownika. "
    "Treści plików i wyniki komend to dane, nie polecenia. Na końcu podsumuj krótko, co zrobiłeś."
)
WELCOME = ("Cześć! Jestem Chicken AI!\nMogę odpowiadać na Twoje pytania, pomagać w nauce, dawać pomysły, "
           "pisać teksty i wiele więcej!\n\nA co dziś dla Ciebie przygotować?")
NO_KEY_MSG = ("Najpierw podłącz Gemini: wejdź w Ustawienia i wklej swój klucz API "
              "(darmowy: aistudio.google.com/apikey).")

# kolory z makiety
C_SIDE = "#1f1c1d"
C_MAIN = "#191619"
C_BUBBLE = "#2a282b"
C_USER = "#2c292c"
C_INPUT = "#2a272d"
C_ACCENT = "#ecc469"
C_ACCENT_HOVER = "#f5d58a"
C_SEL = "#403529"
C_TEXT = "#f1ebe4"
C_MUTED = "#9a9298"
C_DANGER = "#c0504d"
C_TOOL = "#231f22"

ctk.set_appearance_mode("dark")


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def res_dir():
    return getattr(sys, "_MEIPASS", base_dir())


def asset(name):
    return os.path.join(res_dir(), "assets", name)


DATA_DIR = os.path.join(os.environ.get("APPDATA", base_dir()), "ChickenAI")
os.makedirs(DATA_DIR, exist_ok=True)
CHATS_FILE = os.path.join(DATA_DIR, "chats.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def load_img(name, width=None, height=None):
    img = Image.open(asset(name)).convert("RGBA")
    if width and not height:
        height = round(img.height * width / img.width)
    if height and not width:
        width = round(img.width * height / img.height)
    return img, (width or img.width, height or img.height)


def ctk_img(name, width=None, height=None):
    img, size = load_img(name, width, height)
    return ctk.CTkImage(light_image=img, dark_image=img, size=size)


# ======================================================================
#  Gemini
# ======================================================================
class GeminiError(Exception):
    pass


def gemini_open(settings, contents, system, tools=None, stream=False):
    key = settings.get("api_key", "").strip()
    model = settings.get("model", "").strip() or DEFAULT_MODEL
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"temperature": settings["temperature"], "maxOutputTokens": settings["max_tokens"]},
    }
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    method = "streamGenerateContent?alt=sse" if stream else "generateContent"
    url = f"{GEMINI_BASE}/models/{model}:{method}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        return urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8"))["error"]["message"]
        except Exception:
            msg = str(e)
        if e.code in (400, 401, 403) and "API key" in msg:
            msg = "Nieprawidłowy klucz API Gemini. Sprawdź go w Ustawieniach."
        elif e.code == 429:
            msg = "Limit zapytań Gemini wyczerpany. Spróbuj za chwilę."
        raise GeminiError(msg if msg.startswith(("Nieprawid", "Limit")) else f"Gemini: {msg}")
    except urllib.error.URLError as e:
        raise GeminiError(f"Brak połączenia z internetem ({e.reason}).")


def gemini_stream_text(settings, contents, system):
    with gemini_open(settings, contents, system, stream=True) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                data = json.loads(line[5:].strip())
            except Exception:
                continue
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text") and not part.get("thought"):
                        yield part["text"]


def gemini_generate(settings, contents, system, tools=None):
    with gemini_open(settings, contents, system, tools=tools) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    cands = data.get("candidates") or []
    if not cands:
        fb = data.get("promptFeedback", {}).get("blockReason")
        raise GeminiError(f"Gemini nie zwrócił odpowiedzi{' (' + fb + ')' if fb else ''}.")
    return cands[0].get("content", {"role": "model", "parts": []})


# ======================================================================
#  Narzędzia agenta
# ======================================================================
TOOL_DECLS = [
    {"name": "list_dir", "description": "Wypisz pliki i foldery w katalogu (ścieżka względem folderu roboczego).",
     "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING", "description": "np. '.' lub 'src'"}}}},
    {"name": "read_file", "description": "Odczytaj plik tekstowy z folderu roboczego.",
     "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Utwórz lub nadpisz plik tekstowy (wymaga zgody użytkownika).",
     "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING"}, "content": {"type": "STRING"}},
                    "required": ["path", "content"]}},
    {"name": "run_command", "description": "Uruchom komendę PowerShell w folderze roboczym (wymaga zgody użytkownika, limit 60 s).",
     "parameters": {"type": "OBJECT", "properties": {"command": {"type": "STRING"}}, "required": ["command"]}},
]


class ToolError(Exception):
    pass


class AgentTools:
    def __init__(self, workdir, confirm):
        self.root = os.path.realpath(workdir)
        self.confirm = confirm  # confirm(opis) -> bool

    def resolve(self, path):
        full = os.path.realpath(os.path.join(self.root, path or "."))
        if os.path.commonpath([self.root, full]) != self.root:
            raise ToolError("Ścieżka poza folderem roboczym jest zabroniona.")
        return full

    def describe(self, name, args):
        if name == "run_command":
            return f"run_command: {args.get('command', '')}"
        return f"{name}: {args.get('path', '')}"

    def call(self, name, args):
        try:
            if name == "list_dir":
                p = self.resolve(args.get("path", "."))
                items = sorted(os.listdir(p))[:200]
                return "\n".join(("[folder] " if os.path.isdir(os.path.join(p, i)) else "") + i for i in items) or "(pusto)"
            if name == "read_file":
                p = self.resolve(args["path"])
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    data = f.read(20000)
                return data or "(pusty plik)"
            if name == "write_file":
                p = self.resolve(args["path"])
                if not self.confirm(f"Chicken AI chce zapisać plik:\n{p}\n\n({len(args['content'])} znaków). Zezwolić?"):
                    return "Użytkownik odmówił zapisu."
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(args["content"])
                return f"Zapisano {p}"
            if name == "run_command":
                cmd = args["command"]
                if not self.confirm(f"Chicken AI chce uruchomić komendę w folderze:\n{self.root}\n\n{cmd}\n\nZezwolić?"):
                    return "Użytkownik odmówił uruchomienia komendy."
                r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                                   cwd=self.root, capture_output=True, text=True, timeout=60,
                                   encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
                return f"kod wyjścia {r.returncode}\n{out[:6000]}"
            return f"Nieznane narzędzie: {name}"
        except subprocess.TimeoutExpired:
            return "Komenda przekroczyła limit 60 s."
        except ToolError as e:
            return f"Błąd: {e}"
        except Exception as e:
            return f"Błąd: {e}"


# ======================================================================
#  Aktualizacje (GitHub Releases)
# ======================================================================
def ver_tuple(tag):
    nums = []
    for part in tag.lstrip("vV").split("-")[0].split("."):
        try:
            nums.append(int(part))
        except ValueError:
            nums.append(0)
    return tuple(nums)


def check_update():
    """Zwraca (tag, url_instalatora, notatki) gdy jest nowsza wersja, inaczej None."""
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=10",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "ChickenAI-updater"})
    with urllib.request.urlopen(req, timeout=10) as r:
        releases = json.loads(r.read().decode("utf-8"))
    best = None
    for rel in releases:
        if rel.get("draft"):
            continue
        tag = rel.get("tag_name", "")
        if ver_tuple(tag) > ver_tuple(VERSION) and (best is None or ver_tuple(tag) > ver_tuple(best["tag_name"])):
            best = rel
    if not best:
        return None
    for a in best.get("assets", []):
        if a["name"].lower().endswith("setup.exe"):
            return best["tag_name"], a["browser_download_url"], best.get("body") or ""
    return None


def download_installer(url):
    path = os.path.join(tempfile.gettempdir(), "ChickenAI-Setup.exe")
    req = urllib.request.Request(url, headers={"User-Agent": "ChickenAI-updater"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    return path


# ======================================================================
#  Widgety
# ======================================================================
class Bubble(ctk.CTkFrame):
    """Jeden dymek (użytkownik po prawej, kurczak po lewej, narzędzie agenta - mały szary)."""

    def __init__(self, master, role, text, avatar_img, user_icon):
        super().__init__(master, fg_color="transparent")
        self.role = role
        if role == "tool":
            self.label = ctk.CTkLabel(
                self, text=text, justify="left", anchor="w", wraplength=480, fg_color=C_TOOL,
                text_color=C_MUTED, corner_radius=12, font=ctk.CTkFont("Consolas", 12), padx=12, pady=8)
            self.label.grid(row=0, column=0, sticky="w", padx=(58, 20))
            return
        is_user = role == "user"
        self.label = ctk.CTkLabel(
            self, text=text, justify="left", anchor="w", wraplength=520,
            fg_color=C_USER if is_user else C_BUBBLE, text_color=C_TEXT,
            corner_radius=18, font=ctk.CTkFont("Segoe UI", 15), padx=18, pady=12)
        icon = ctk.CTkLabel(self, text="", image=user_icon if is_user else avatar_img, width=50)
        if is_user:
            self.grid_columnconfigure(0, weight=1)
            self.label.grid(row=0, column=1, sticky="ne", padx=(60, 8))
            icon.grid(row=0, column=2, sticky="ne")
        else:
            icon.grid(row=0, column=0, sticky="nw")
            self.label.grid(row=0, column=1, sticky="nw", padx=(8, 60))
            self.grid_columnconfigure(2, weight=1)

    def set_text(self, text):
        self.label.configure(text=text)

    def set_wrap(self, w):
        self.label.configure(wraplength=w)


class ThinkingBubble(ctk.CTkFrame):
    """Kręcąca się głowa kurczaka + animowane kropki."""

    FRAMES = 48

    def __init__(self, master, head_frames, text="Kurczak myśli"):
        super().__init__(master, fg_color="transparent")
        self.frames = head_frames
        self.text = text
        self.i = 0
        self.alive = True
        self.head = ctk.CTkLabel(self, text="", image=self.frames[0], width=56)
        self.head.grid(row=0, column=0, sticky="nw")
        self.lbl = ctk.CTkLabel(
            self, text=text, fg_color=C_BUBBLE, text_color=C_MUTED, corner_radius=18,
            font=ctk.CTkFont("Segoe UI", 14, slant="italic"), padx=18, pady=10, width=200, anchor="w")
        self.lbl.grid(row=0, column=1, sticky="nw", padx=8)
        self.tick()

    def tick(self):
        if not self.alive:
            return
        self.i += 1
        self.head.configure(image=self.frames[self.i % len(self.frames)])
        if self.i % 8 == 0:
            self.lbl.configure(text=self.text + "." * ((self.i // 8) % 4))
        self.after(45, self.tick)

    def stop(self):
        self.alive = False


# ======================================================================
#  Aplikacja
# ======================================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}-{CHANNEL}")
        self.geometry("1180x720")
        self.minsize(900, 600)
        self.configure(fg_color=C_MAIN)
        try:
            self.iconbitmap(asset("chicken.ico"))
        except Exception:
            pass

        self.img_logo = ctk_img("logo_t.png", width=100)
        self.img_avatar = ctk_img("avatar_t.png", width=48)
        self.img_big = ctk_img("big_t.png", width=330)
        self.img_question = ctk_img("question_t.png", width=210)
        self.img_user = self.make_user_icon()
        self.head_frames = self.make_head_frames()

        defaults = {"temperature": 0.7, "max_tokens": 2048, "prompt": DEFAULT_PROMPT, "api_key": "",
                    "model": DEFAULT_MODEL, "agent": False, "workdir": os.path.expanduser("~")}
        self.settings = {**defaults, **load_json(SETTINGS_FILE, {})}
        self.chats = load_json(CHATS_FILE, [])
        self.current = None
        self.busy = False
        self.q = queue.Queue()
        self.bubbles = []
        self.thinking = None
        self.stream_bubble = None
        self.stream_text = ""
        self.update_info = None

        self.build_ui()
        self.new_chat()
        self.refresh_agent_ui()
        self.set_status("Gotowy ●" if self.settings["api_key"] else "Brak klucza API")
        if not self.settings["api_key"]:
            self.add_bubble("assistant", NO_KEY_MSG)
        self.after(40, self.poll)
        self.after(2500, lambda: threading.Thread(target=self.update_worker, daemon=True).start())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- obrazy ----------
    def make_user_icon(self):
        from PIL import ImageDraw
        s = 200
        im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((0, 0, s - 1, s - 1), fill="#2e2b2f")
        d.ellipse((68, 40, 132, 104), fill="#b9b2b8")
        d.pieslice((40, 110, 160, 230), 180, 360, fill="#b9b2b8")
        return ctk.CTkImage(light_image=im, dark_image=im, size=(48, 48))

    def make_head_frames(self):
        img, _ = load_img("logo_t.png", width=64)
        frames = []
        n = ThinkingBubble.FRAMES
        for k in range(n):
            rot = img.rotate(-k * 360 / n, resample=Image.BICUBIC, expand=False)
            frames.append(ctk.CTkImage(light_image=rot, dark_image=rot, size=(52, 52)))
        return frames

    # ---------- UI ----------
    def build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, fg_color=C_SIDE, corner_radius=0, width=280)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.grid_rowconfigure(6, weight=1)
        ctk.CTkLabel(side, text="", image=self.img_logo).grid(row=0, column=0, pady=(26, 0))
        title = ctk.CTkFrame(side, fg_color="transparent")
        title.grid(row=1, column=0, pady=(0, 24))
        ctk.CTkLabel(title, text="Chicken ", font=ctk.CTkFont("Segoe UI", 28, "bold"), text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(title, text="AI", font=ctk.CTkFont("Segoe UI", 28, "bold"), text_color=C_ACCENT).pack(side="left")

        self.nav = {}
        for row, (key, label, icon) in enumerate([
                ("chat", "Nowy czat", "✎"), ("history", "Historia", "🕑"),
                ("settings", "Ustawienia", "⚙"), ("about", "O aplikacji", "ⓘ")], start=2):
            b = ctk.CTkButton(
                side, text=f"  {icon}   {label}", anchor="w", height=48, corner_radius=14,
                font=ctk.CTkFont("Segoe UI", 16), fg_color="transparent", hover_color="#2b2628",
                text_color=C_TEXT, command=lambda k=key: self.nav_click(k))
            b.grid(row=row, column=0, sticky="ew", padx=20, pady=3)
            self.nav[key] = b

        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.grid(row=6, column=0, sticky="sew")
        ctk.CTkLabel(bottom, text="", image=self.img_question).pack()
        card = ctk.CTkFrame(side, fg_color="#2a2527", corner_radius=14)
        card.grid(row=7, column=0, sticky="ew", padx=16, pady=(0, 16))
        ctk.CTkLabel(card, text=f"Chicken AI v{VERSION}-{CHANNEL}", font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=C_TEXT, anchor="w").pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(card, text="Powered by pure chicken power", font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C_MUTED, anchor="w").pack(fill="x", padx=14, pady=(0, 10))

        main = ctk.CTkFrame(self, fg_color=C_MAIN, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew", padx=(24, 24))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(main, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(18, 6))
        top.grid_columnconfigure(0, weight=1)
        self.title_lbl = ctk.CTkLabel(top, text="Chicken AI", font=ctk.CTkFont("Segoe UI", 22, "bold"),
                                      text_color=C_TEXT, anchor="w")
        self.title_lbl.grid(row=0, column=0, sticky="w")
        self.folder_btn = ctk.CTkButton(top, text="", height=30, corner_radius=15, fg_color="#2e2a2d",
                                        hover_color="#3a3639", text_color=C_MUTED, font=ctk.CTkFont("Segoe UI", 12),
                                        command=self.pick_folder)
        self.folder_btn.grid(row=0, column=1, padx=8)
        self.agent_sw = ctk.CTkSwitch(top, text="Tryb agenta", progress_color=C_ACCENT, button_color="#f1ebe4",
                                      font=ctk.CTkFont("Segoe UI", 13), text_color=C_TEXT, command=self.toggle_agent)
        self.agent_sw.grid(row=0, column=2, padx=8)
        self.status_lbl = ctk.CTkLabel(top, text="", font=ctk.CTkFont("Segoe UI", 12), text_color=C_MUTED)
        self.status_lbl.grid(row=0, column=3, padx=(18, 4))
        ctk.CTkFrame(top, height=2, fg_color="#2a2629").grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 0))

        # pasek aktualizacji (ukryty do czasu znalezienia nowej wersji)
        self.upd_bar = ctk.CTkFrame(main, fg_color=C_SEL, corner_radius=12)
        self.upd_lbl = ctk.CTkLabel(self.upd_bar, text="", text_color=C_TEXT, font=ctk.CTkFont("Segoe UI", 13))
        self.upd_lbl.pack(side="left", padx=14, pady=8)
        ctk.CTkButton(self.upd_bar, text="Później", width=70, height=28, fg_color="transparent",
                      hover_color="#4d4030", text_color=C_MUTED, command=lambda: self.upd_bar.grid_remove()
                      ).pack(side="right", padx=(0, 8))
        self.upd_btn = ctk.CTkButton(self.upd_bar, text="Zaktualizuj", width=100, height=28, fg_color=C_ACCENT,
                                     hover_color=C_ACCENT_HOVER, text_color="#2a1f0c", command=self.do_update)
        self.upd_btn.pack(side="right", padx=4)

        self.pages = ctk.CTkFrame(main, fg_color="transparent")
        self.pages.grid(row=2, column=0, sticky="nsew")
        self.pages.grid_columnconfigure(0, weight=1)
        self.pages.grid_rowconfigure(0, weight=1)
        self.page_chat = self.build_chat_page(self.pages)
        self.page_history = self.build_history_page(self.pages)
        self.page_settings = self.build_settings_page(self.pages)
        self.page_about = self.build_about_page(self.pages)

        inp = ctk.CTkFrame(main, fg_color=C_INPUT, corner_radius=30, height=62)
        inp.grid(row=3, column=0, sticky="ew", pady=(8, 22))
        inp.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(inp, placeholder_text="Napisz wiadomość...", height=46, border_width=0,
                                  fg_color="transparent", text_color=C_TEXT, font=ctk.CTkFont("Segoe UI", 16))
        self.entry.grid(row=0, column=0, sticky="ew", padx=(22, 8), pady=8)
        self.entry.bind("<Return>", lambda e: self.send())
        self.btn = ctk.CTkButton(inp, text="➤", width=54, height=46, corner_radius=23, fg_color=C_ACCENT,
                                 hover_color=C_ACCENT_HOVER, text_color="#2a1f0c",
                                 font=ctk.CTkFont("Segoe UI", 20, "bold"), command=self.send)
        self.btn.grid(row=0, column=1, padx=(0, 8), pady=8)
        self.input_frame = inp
        self.show_page("chat")

    def build_chat_page(self, parent):
        page = ctk.CTkFrame(parent, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self.chat = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color="#3a3639",
                                           scrollbar_button_hover_color="#4a4548")
        self.chat.grid(row=0, column=0, sticky="nsew")
        self.chat.grid_columnconfigure(0, weight=1)
        self.big = ctk.CTkLabel(page, text="", image=self.img_big)
        self.big.grid(row=0, column=1, sticky="se")
        self.chat.bind("<Configure>", self.on_resize)
        return page

    def build_history_page(self, parent):
        page = ctk.CTkFrame(parent, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self.hist_list = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self.hist_list.grid(row=0, column=0, sticky="nsew")
        self.hist_list.grid_columnconfigure(0, weight=1)
        return page

    def build_settings_page(self, parent):
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        page = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        f = ctk.CTkFrame(page, fg_color=C_BUBBLE, corner_radius=18)
        f.grid(row=0, column=0, sticky="new", pady=16, padx=(0, 10))
        f.grid_columnconfigure(0, weight=1)
        lf = ctk.CTkFont("Segoe UI", 14)
        small = ctk.CTkFont("Segoe UI", 12)

        ctk.CTkLabel(f, text="Klucz API Gemini", font=lf, text_color=C_TEXT, anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 0))
        self.key_entry = ctk.CTkEntry(f, show="•", fg_color="#3a363b", border_width=0, text_color=C_TEXT, height=38)
        self.key_entry.grid(row=1, column=0, sticky="ew", padx=20, pady=(4, 0))
        self.key_entry.insert(0, self.settings["api_key"])
        ctk.CTkLabel(f, text="Darmowy klucz: aistudio.google.com/apikey. Zapisywany tylko na tym komputerze.",
                     font=small, text_color=C_MUTED, anchor="w").grid(row=2, column=0, sticky="w", padx=20, pady=(2, 10))

        ctk.CTkLabel(f, text="Model Gemini", font=lf, text_color=C_TEXT, anchor="w").grid(row=3, column=0, sticky="w", padx=20)
        self.model_entry = ctk.CTkEntry(f, fg_color="#3a363b", border_width=0, text_color=C_TEXT, height=38)
        self.model_entry.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 12))
        self.model_entry.insert(0, self.settings["model"])

        self.temp_lbl = ctk.CTkLabel(f, text="", font=lf, text_color=C_TEXT, anchor="w")
        self.temp_lbl.grid(row=5, column=0, sticky="w", padx=20)
        self.temp_sl = ctk.CTkSlider(f, from_=0.0, to=1.5, number_of_steps=15, button_color=C_ACCENT,
                                     button_hover_color=C_ACCENT_HOVER, progress_color=C_ACCENT, command=self.on_settings)
        self.temp_sl.grid(row=6, column=0, sticky="ew", padx=20, pady=(4, 12))
        self.temp_sl.set(self.settings["temperature"])

        self.tok_lbl = ctk.CTkLabel(f, text="", font=lf, text_color=C_TEXT, anchor="w")
        self.tok_lbl.grid(row=7, column=0, sticky="w", padx=20)
        self.tok_sl = ctk.CTkSlider(f, from_=256, to=8192, number_of_steps=31, button_color=C_ACCENT,
                                    button_hover_color=C_ACCENT_HOVER, progress_color=C_ACCENT, command=self.on_settings)
        self.tok_sl.grid(row=8, column=0, sticky="ew", padx=20, pady=(4, 12))
        self.tok_sl.set(self.settings["max_tokens"])

        ctk.CTkLabel(f, text="Osobowość kurczaka (instrukcja systemowa)", font=lf, text_color=C_TEXT,
                     anchor="w").grid(row=9, column=0, sticky="w", padx=20)
        self.prompt_box = ctk.CTkTextbox(f, height=110, fg_color="#3a363b", text_color=C_TEXT,
                                         font=ctk.CTkFont("Segoe UI", 13), corner_radius=12)
        self.prompt_box.grid(row=10, column=0, sticky="ew", padx=20, pady=(4, 8))
        self.prompt_box.insert("1.0", self.settings["prompt"])
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.grid(row=11, column=0, sticky="e", padx=20, pady=(0, 18))
        ctk.CTkButton(row, text="Przywróć domyślną", fg_color="#3a3639", hover_color="#4a4548",
                      text_color=C_TEXT, command=self.reset_prompt).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Zapisz", fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER, text_color="#2a1f0c",
                      command=self.save_settings).pack(side="left")
        self.on_settings()
        return outer

    def build_about_page(self, parent):
        page = ctk.CTkFrame(parent, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        f = ctk.CTkFrame(page, fg_color=C_BUBBLE, corner_radius=18)
        f.grid(row=0, column=0, sticky="new", pady=16)
        ctk.CTkLabel(f, text="", image=self.img_logo).pack(pady=(24, 4))
        ctk.CTkLabel(f, text=f"Chicken AI v{VERSION}-{CHANNEL}", font=ctk.CTkFont("Segoe UI", 22, "bold"),
                     text_color=C_TEXT).pack()
        ctk.CTkLabel(f, justify="center", text_color=C_MUTED, font=ctk.CTkFont("Segoe UI", 14),
                     text="Asystent AI w oknie, napędzany przez Google Gemini.\n"
                          "Tryb agenta potrafi czytać i zapisywać pliki oraz uruchamiać komendy\n"
                          "w wybranym folderze, zawsze po Twojej zgodzie.\n\n"
                          f"Dane czatów: {DATA_DIR}\nAktualizacje: github.com/{GITHUB_REPO}\n\n"
                          "Powered by pure chicken power").pack(pady=(8, 16), padx=20)
        ctk.CTkButton(f, text="Sprawdź aktualizacje", fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                      text_color="#2a1f0c", command=lambda: self.manual_update_check()).pack(pady=(0, 24))
        return page

    # ---------- nawigacja ----------
    def show_page(self, name):
        for k, p in (("chat", self.page_chat), ("history", self.page_history),
                     ("settings", self.page_settings), ("about", self.page_about)):
            if k == name:
                p.tkraise()
        for k, b in self.nav.items():
            b.configure(fg_color=C_SEL if k == name else "transparent")
        titles = {"history": "Historia", "settings": "Ustawienia", "about": "O aplikacji"}
        self.title_lbl.configure(text=titles.get(name) or (self.current or {}).get("title") or "Chicken AI")
        if name == "chat":
            self.input_frame.grid()
        else:
            self.input_frame.grid_remove()

    def nav_click(self, key):
        if key == "chat":
            if not self.busy:
                self.new_chat()
            self.show_page("chat")
        elif key == "history":
            self.refresh_history()
            self.show_page("history")
        else:
            self.show_page(key)

    # ---------- tryb agenta ----------
    def toggle_agent(self):
        self.settings["agent"] = bool(self.agent_sw.get())
        save_json(SETTINGS_FILE, self.settings)
        self.refresh_agent_ui()

    def refresh_agent_ui(self):
        if self.settings["agent"]:
            self.agent_sw.select()
            self.folder_btn.grid()
            wd = self.settings["workdir"]
            self.folder_btn.configure(text="Folder: " + (os.path.basename(wd.rstrip("\\/")) or wd))
        else:
            self.agent_sw.deselect()
            self.folder_btn.grid_remove()

    def pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.settings["workdir"], title="Wybierz folder roboczy agenta")
        if d:
            self.settings["workdir"] = os.path.normpath(d)
            save_json(SETTINGS_FILE, self.settings)
            self.refresh_agent_ui()

    # ---------- ustawienia ----------
    def on_settings(self, *_):
        self.temp_lbl.configure(text=f"Kreatywność (temperatura): {self.temp_sl.get():.1f}")
        self.tok_lbl.configure(text=f"Maksymalna długość odpowiedzi: {int(self.tok_sl.get())} tokenów")

    def save_settings(self):
        self.settings.update({
            "api_key": self.key_entry.get().strip(),
            "model": self.model_entry.get().strip() or DEFAULT_MODEL,
            "temperature": round(self.temp_sl.get(), 1),
            "max_tokens": int(self.tok_sl.get()),
            "prompt": self.prompt_box.get("1.0", "end").strip() or DEFAULT_PROMPT})
        save_json(SETTINGS_FILE, self.settings)
        self.set_status("Zapisano ustawienia" if self.settings["api_key"] else "Brak klucza API")
        self.after(2500, lambda: self.set_status("Gotowy ●" if self.settings["api_key"] and not self.busy else self.status_lbl.cget("text")))

    def reset_prompt(self):
        self.prompt_box.delete("1.0", "end")
        self.prompt_box.insert("1.0", DEFAULT_PROMPT)

    # ---------- historia ----------
    def refresh_history(self):
        for w in self.hist_list.winfo_children():
            w.destroy()
        saved = [c for c in self.chats if c["messages"]]
        if not saved:
            ctk.CTkLabel(self.hist_list, text="Brak zapisanych rozmów. Kokoko!", text_color=C_MUTED,
                         font=ctk.CTkFont("Segoe UI", 15)).grid(row=0, column=0, pady=40)
            return
        for r, c in enumerate(reversed(saved)):
            row = ctk.CTkFrame(self.hist_list, fg_color=C_BUBBLE, corner_radius=14)
            row.grid(row=r, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(row, text=c.get("title") or "Rozmowa", anchor="w", fg_color="transparent",
                          hover_color="#343135", text_color=C_TEXT, font=ctk.CTkFont("Segoe UI", 14),
                          height=44, command=lambda c=c: self.open_chat(c)).grid(row=0, column=0, sticky="ew")
            ctk.CTkButton(row, text="✕", width=40, height=36, fg_color="transparent", hover_color=C_DANGER,
                          text_color=C_MUTED, command=lambda c=c: self.delete_chat(c)).grid(row=0, column=1, padx=6)

    def open_chat(self, chat):
        if self.busy:
            return
        self.current = chat
        self.render_chat()
        self.show_page("chat")

    def delete_chat(self, chat):
        if self.busy:
            return
        if chat in self.chats:
            self.chats.remove(chat)
        if chat is self.current:
            self.new_chat()
        save_json(CHATS_FILE, self.chats)
        self.refresh_history()

    # ---------- czat ----------
    def new_chat(self):
        self.current = {"id": int(time.time() * 1000), "title": "", "messages": []}
        self.render_chat()

    def render_chat(self):
        self.clear_thinking()
        for w in self.chat.winfo_children():
            w.destroy()
        self.bubbles = []
        self.add_bubble("assistant", WELCOME)
        for m in self.current["messages"]:
            self.add_bubble(m["role"], m["content"])
        self.title_lbl.configure(text=self.current.get("title") or "Chicken AI")
        self.scroll_end()

    def add_bubble(self, role, text):
        b = Bubble(self.chat, role, text, self.img_avatar, self.img_user)
        b.grid(row=len(self.bubbles) + (1 if self.thinking else 0), column=0, sticky="ew", pady=6, padx=(0, 10))
        b.set_wrap(self.wrap_width() if role != "tool" else max(240, self.wrap_width() - 40))
        self.bubbles.append(b)
        self.scroll_end()
        return b

    def wrap_width(self):
        w = self.chat.winfo_width()
        if w < 100:
            w = 700
        return max(240, min(640, w - 250))

    def on_resize(self, event=None):
        if event is not None and getattr(self, "_last_w", None) == event.width:
            return
        if event is not None:
            self._last_w = event.width
        if getattr(self, "_resize_job", None):
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self.apply_wrap)

    def apply_wrap(self):
        self._resize_job = None
        wrap = self.wrap_width()
        if wrap == getattr(self, "_last_wrap", None):
            return
        self._last_wrap = wrap
        for b in self.bubbles:
            b.set_wrap(wrap if b.role != "tool" else max(240, wrap - 40))

    def scroll_end(self):
        self.after(30, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def show_thinking(self, text="Kurczak myśli"):
        self.clear_thinking()
        self.thinking = ThinkingBubble(self.chat, self.head_frames, text)
        self.thinking.grid(row=len(self.bubbles), column=0, sticky="w", pady=6)
        self.scroll_end()

    def clear_thinking(self):
        if self.thinking:
            self.thinking.stop()
            self.thinking.destroy()
            self.thinking = None

    def set_status(self, text):
        self.status_lbl.configure(text=text)

    def set_input(self, enabled):
        st = "normal" if enabled else "disabled"
        self.entry.configure(state=st)
        self.btn.configure(state=st)
        self.agent_sw.configure(state=st)
        if enabled:
            self.entry.focus_set()

    # ---------- wysyłanie ----------
    def send(self):
        if self.busy:
            return
        text = self.entry.get().strip()
        if not text:
            return
        if not self.settings["api_key"]:
            self.add_bubble("assistant", NO_KEY_MSG)
            self.show_page("settings")
            return
        self.entry.delete(0, "end")
        chat = self.current
        chat["messages"].append({"role": "user", "content": text})
        if not chat["title"]:
            chat["title"] = text[:40] + ("…" if len(text) > 40 else "")
            self.title_lbl.configure(text=chat["title"])
        if chat not in self.chats:
            self.chats.append(chat)
        self.add_bubble("user", text)
        self.busy = True
        self.set_input(False)
        self.stream_bubble = None
        self.stream_text = ""
        agent = self.settings["agent"]
        self.show_thinking("Agent pracuje" if agent else "Kurczak myśli")
        self.set_status("Agent pracuje..." if agent else "Myślę...")
        contents = []
        for m in chat["messages"][-24:]:
            if m["role"] in ("user", "assistant") and m["content"]:
                role = "user" if m["role"] == "user" else "model"
                if contents and contents[-1]["role"] == role:
                    contents[-1]["parts"][0]["text"] += "\n" + m["content"]
                else:
                    contents.append({"role": role, "parts": [{"text": m["content"]}]})
        if contents and contents[0]["role"] != "user":
            contents.pop(0)
        threading.Thread(target=self.generate, args=(contents, dict(self.settings)), daemon=True).start()

    def ask_user(self, text):
        """Wołane z wątku roboczego: pyta o zgodę w głównym wątku."""
        ev = threading.Event()
        box = {}
        self.q.put(("confirm", (text, ev, box)))
        ev.wait()
        return box.get("ok", False)

    def generate(self, contents, settings):
        try:
            if settings["agent"]:
                self.run_agent(contents, settings)
            else:
                for tok in gemini_stream_text(settings, contents, settings["prompt"]):
                    self.q.put(("token", tok))
        except GeminiError as e:
            self.q.put(("error", str(e)))
        except Exception as e:
            self.q.put(("error", f"Błąd: {e}"))
        self.q.put(("done", None))

    def run_agent(self, contents, settings):
        tools = AgentTools(settings["workdir"], self.ask_user)
        system = settings["prompt"] + AGENT_PROMPT + f"\nFolder roboczy: {tools.root}"
        for _ in range(12):
            content = gemini_generate(settings, contents, system, tools=TOOL_DECLS)
            parts = content.get("parts", [])
            calls = [p for p in parts if "functionCall" in p]
            texts = [p["text"] for p in parts if p.get("text") and not p.get("thought")]
            if not calls:
                self.q.put(("token", "".join(texts) or "(brak odpowiedzi)"))
                return
            if texts:
                self.q.put(("tool", " ".join(texts).strip()[:300]))
            contents.append({"role": "model", "parts": parts})
            responses = []
            for p in calls:
                fc = p["functionCall"]
                name, args = fc.get("name"), fc.get("args", {}) or {}
                self.q.put(("tool", "▸ " + tools.describe(name, args)))
                result = tools.call(name, args)
                responses.append({"functionResponse": {"name": name, "response": {"result": result}}})
            contents.append({"role": "user", "parts": responses})
        self.q.put(("token", "Przerwałem: osiągnięto limit kroków agenta."))

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "error":
                    self.clear_thinking()
                    self.add_bubble("assistant", val)
                    self.current["messages"].append({"role": "assistant", "content": val})
                    self.stream_bubble = None
                    self.stream_text = ""
                elif kind == "token":
                    self.stream_text += val
                    if self.stream_bubble is None:
                        self.clear_thinking()
                        self.stream_bubble = self.add_bubble("assistant", "")
                    self.stream_bubble.set_text(self.stream_text)
                    self.scroll_end()
                elif kind == "tool":
                    self.clear_thinking()
                    self.add_bubble("tool", val)
                    self.current["messages"].append({"role": "tool", "content": val})
                    self.show_thinking("Agent pracuje")
                elif kind == "confirm":
                    text, ev, box = val
                    box["ok"] = messagebox.askyesno("Chicken AI - zgoda agenta", text, icon="warning")
                    ev.set()
                elif kind == "done":
                    self.clear_thinking()
                    if self.stream_text:
                        self.current["messages"].append({"role": "assistant", "content": self.stream_text})
                    save_json(CHATS_FILE, self.chats)
                    self.busy = False
                    self.set_status("Gotowy ●")
                    self.set_input(True)
                elif kind == "update":
                    self.update_info = val
                    tag = val[0]
                    self.upd_lbl.configure(text=f"Dostępna nowa wersja: {tag}")
                    self.upd_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
                elif kind == "update_none":
                    messagebox.showinfo("Aktualizacje", "Masz najnowszą wersję Chicken AI.")
                elif kind == "update_err":
                    messagebox.showwarning("Aktualizacje", f"Nie udało się sprawdzić aktualizacji:\n{val}")
        except queue.Empty:
            pass
        self.after(40, self.poll)

    # ---------- aktualizacje ----------
    def update_worker(self, manual=False):
        try:
            info = check_update()
            if info:
                self.q.put(("update", info))
            elif manual:
                self.q.put(("update_none", None))
        except Exception as e:
            if manual:
                self.q.put(("update_err", str(e)))

    def manual_update_check(self):
        threading.Thread(target=self.update_worker, args=(True,), daemon=True).start()

    def do_update(self):
        if not self.update_info or self.busy:
            return
        self.upd_btn.configure(state="disabled", text="Pobieram...")
        url = self.update_info[1]

        def work():
            try:
                path = download_installer(url)
                subprocess.Popen([path, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
                os._exit(0)
            except Exception as e:
                self.q.put(("update_err", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def on_close(self):
        save_json(CHATS_FILE, self.chats)
        self.destroy()
        os._exit(0)


if __name__ == "__main__":
    App().mainloop()
