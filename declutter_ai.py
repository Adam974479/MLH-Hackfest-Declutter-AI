# [1] — Same imports from both scripts + extras
import os, sys, shutil, json, re, hashlib, zipfile, subprocess, platform, ctypes, dotenv
import tkinter as tk
from tkinter import filedialog, messagebox, Canvas, Frame, Scrollbar
from PIL import Image, ImageTk
import google.generativeai as genai

# [2] — Asset path resolver (for PyInstaller compatibility)
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

# [3] — DPI Fix
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
except Exception:
    scale = 1.0

# [4] — Load sprite images
def load_image(path, size=None, scale=None):
    try:
        img = Image.open(path)
        if scale:
            width, height = img.size
            img = img.resize((int(width * scale), int(height * scale)), Image.NEAREST)
        elif size:
            img = img.resize(size, Image.NEAREST)
        return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"[Warning] Could not load image '{path}': {e}")
        return None

# [5] — Placeholder helper
def add_placeholder(entry_widget, placeholder_text, color="#999999"):
    def on_focus_in(event):
        if entry_widget.get() == placeholder_text:
            entry_widget.delete(0, tk.END)
            entry_widget.config(fg="#000000")
    def on_focus_out(event):
        if not entry_widget.get():
            entry_widget.insert(0, placeholder_text)
            entry_widget.config(fg=color)
    entry_widget.insert(0, placeholder_text)
    entry_widget.config(fg=color)
    entry_widget.bind("<FocusIn>", on_focus_in)
    entry_widget.bind("<FocusOut>", on_focus_out)

# [6] — Gemini
genai.configure(api_key=dotenv.get_key(".env", "GEMINI_API_KEY"))
model = genai.GenerativeModel("models/gemini-1.5-pro")

def call_gemini_api(file_data, user_prompt):
    prompt = (
        "You are an expert assistant inside 'Declutter AI'."
        " Return a JSON mapping filenames to folder names only.\n\n"
        f"User context:\n{user_prompt}\n\nFiles:\n{json.dumps(file_data, indent=2)}"
    )
    response = model.generate_content(prompt)
    cleaned = re.sub(r"^```(?:json)?|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)

def chat_with_ai(file_data, chat_history, message):
    prompt = (
        "You are a friendly AI assistant embedded in an app called 'Declutter AI'.\n"
        "You help users decide how to group and organize files by name and type.\n"
        f"Here is the current list of files to be sorted:\n{json.dumps(file_data, indent=2)}\n\n"
        "Conversation so far:\n"
    )
    for role, msg in chat_history:
        prompt += f"{role}: {msg}\n"
    prompt += f"User: {message}\nAI:"

    response = model.generate_content(prompt)
    return response.text.strip()


# [7] — Duplicate detection
def compute_file_hash(filepath):
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def find_and_handle_duplicates(folder_path):
    hash_map, keepers, duplicates = {}, {}, []
    for filename in os.listdir(folder_path):
        full_path = os.path.join(folder_path, filename)
        if os.path.isfile(full_path):
            file_hash = compute_file_hash(full_path)
            hash_map.setdefault(file_hash, []).append((full_path, os.path.getmtime(full_path)))

    for files in hash_map.values():
        if len(files) > 1:
            files.sort(key=lambda x: x[1], reverse=True)
            keep = files[0][0]
            keepers[keep] = True
            for dup_path, _ in files[1:]:
                duplicates.append(dup_path)
        else:
            keepers[files[0][0]] = True

    return duplicates, list(keepers.keys())

def zip_duplicates(duplicates, folder_path, delete=False):
    zip_path = os.path.join(folder_path, "duplicates_backup.zip")
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for dup in duplicates:
            zipf.write(dup, os.path.basename(dup))
            if delete:
                os.remove(dup)
    return zip_path

# [8] — App class with all logic
class DeclutterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Folder Declutter")
        self.root.geometry(f"{int(600*scale)}x{int(700*scale)}")
        self.root.configure(bg="#fbeac7")

        font_label = ("Courier", int(12 * scale))

        self.browse_img = load_image(os.path.join(ASSETS_DIR, "Browse.png"), scale=4)
        self.sort_img = load_image(os.path.join(ASSETS_DIR, "sort.png"), scale=4)
        self.star_img = load_image(os.path.join(ASSETS_DIR, "star.png"), scale=4)
        self.newFolder_img = load_image(os.path.join(ASSETS_DIR, "new folder.png"), scale=4)

        # Title
        tk.Label(root, text="📁 Declutter AI", font=("Courier", int(16*scale), "bold"), bg="#fbeac7").pack(pady=int(10*scale))

        # Folder input
        self.folder_frame = tk.Frame(root, bg="#fbeac7")
        self.folder_frame.pack(padx=10, pady=4, fill="x")
        self.folder_path_display = tk.Entry(self.folder_frame, font=font_label, bg="#fff7dc")
        self.folder_path_display.pack(side=tk.LEFT, expand=True, fill="x", padx=4)
        add_placeholder(self.folder_path_display, "paste file directory...")
        self.select_button = tk.Button(self.folder_frame, image=self.browse_img, command=self.select_folder, bd=0, bg="#fbeac7")
        self.select_button.pack(side=tk.LEFT)

        # Chat area
        self.chat_container = Frame(root, bg="#fbeac7")
        self.chat_container.pack(pady=(10, 5), fill=tk.BOTH, expand=True)
        self.chat_canvas = Canvas(self.chat_container, bg="#fff7dc", highlightthickness=0)
        self.chat_scrollbar = Scrollbar(self.chat_container, command=self.chat_canvas.yview)
        self.chat_frame = Frame(self.chat_canvas, bg="#fff7dc")
        self.chat_frame.bind("<Configure>", lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all")))
        self.chat_canvas.create_window((0, 0), window=self.chat_frame, anchor="nw")
        self.chat_canvas.configure(yscrollcommand=self.chat_scrollbar.set)
        self.chat_canvas.pack(side="left", fill="both", expand=True)
        self.chat_scrollbar.pack(side="right", fill="y")

        # Chat input
        self.input_frame = tk.Frame(root, bg="#fbeac7")
        self.input_frame.pack()
        self.chat_entry = tk.Entry(self.input_frame, width=45, font=font_label, bg="#fff7dc")
        self.chat_entry.pack(pady=3)
        add_placeholder(self.chat_entry, "type here...")
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())
        self.chat_button = tk.Button(self.input_frame, image=self.star_img, command=self.send_chat, bd=0, bg="#fbeac7")
        self.chat_button.pack()

        # Sort / Reset buttons
        self.sort_button = tk.Button(self.input_frame, image=self.sort_img, command=self.process_folder, bd=0, bg="#fbeac7", state=tk.DISABLED)
        self.sort_button.pack(pady=3)
        self.reset_button = tk.Button(self.input_frame, image=self.newFolder_img, command=self.reset_app, bd=0, bg="#fbeac7", state=tk.DISABLED)
        self.reset_button.pack()

        self.status_label = tk.Label(root, text="", font=font_label, bg="#fbeac7", fg="green")
        self.status_label.pack()

        # Init vars
        self.folder_path = ""
        self.file_data = []
        self.chat_history = []
        self.add_message("AI", "Hi! 👋 Ready to organize some files? Select a folder and let’s go!")

    def add_message(self, sender, message):
        label = tk.Label(self.chat_frame, text=f"{sender}: {message}", font=("Courier", int(10 * scale)),
                         wraplength=int(480 * scale), bg="#ffffff" if sender == "AI" else "#e0e0e0",
                         justify="left", anchor="w", padx=10, pady=5, bd=1, relief="solid")
        label.pack(anchor="w" if sender == "You" else "e", pady=4, padx=6, fill="x")
        self.chat_canvas.yview_moveto(1.0)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path = folder
            self.folder_path_display.delete(0, tk.END)
            self.folder_path_display.insert(0, folder)
            self.sort_button.config(state=tk.NORMAL)
            self.reset_button.config(state=tk.DISABLED)
            self.status_label.config(text="")
            self.file_data = [{"name": f, "type": os.path.splitext(f)[1]} for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]

    def send_chat(self):
        msg = self.chat_entry.get()
        if not msg or not self.file_data: return
        self.add_message("You", msg)
        self.chat_entry.delete(0, tk.END)
        self.chat_history.append(("User", msg))
        self.root.update_idletasks()
        label = tk.Label(self.chat_frame, text="AI is thinking...", bg="#fff7dc", font=("Courier", int(10*scale), "italic"))
        label.pack(anchor="e", pady=4, padx=6)
        self.chat_canvas.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)
        try:
            reply = chat_with_ai(self.file_data, self.chat_history, msg)
            label.destroy()
            self.add_message("AI", reply)
            self.chat_history.append(("AI", reply))
        except Exception as e:
            label.destroy()
            self.add_message("AI", f"(Error: {e})")

    def process_folder(self):
        if not self.folder_path: return
        duplicates, keepers = find_and_handle_duplicates(self.folder_path)
        if duplicates:
            zip_path = zip_duplicates(duplicates, self.folder_path, delete=True)
            self.add_message("AI", f"Zipped duplicates into: {zip_path}")

        self.file_data = [{"name": os.path.basename(f), "type": os.path.splitext(f)[1]} for f in keepers if os.path.isfile(f)]
        if not self.file_data:
            messagebox.showinfo("Nothing to sort", "No files to sort after duplicate cleanup.")
            return
        try:
            result = call_gemini_api(self.file_data, self.generate_context_from_chat())
        except Exception as e:
            messagebox.showerror("AI Error", f"Failed: {e}")
            return
        for name, folder in result.items():
            src = os.path.join(self.folder_path, name)
            dst_folder = os.path.join(self.folder_path, folder)
            os.makedirs(dst_folder, exist_ok=True)
            shutil.move(src, os.path.join(dst_folder, name))
        self.status_label.config(text="Sorting complete ✔️")
        self.reset_button.config(state=tk.NORMAL)
        self.add_message("AI", "🎉 Files sorted! Want to do another folder?")

    def generate_context_from_chat(self):
        return "\n".join(f"{r}: {m}" for r, m in self.chat_history if r == "User")

    def reset_app(self):
        self.folder_path = ""
        self.file_data.clear()
        self.chat_history.clear()
        self.folder_path_display.delete(0, tk.END)
        for widget in self.chat_frame.winfo_children(): widget.destroy()
        self.status_label.config(text="")
        self.sort_button.config(state=tk.DISABLED)
        self.reset_button.config(state=tk.DISABLED)
        self.add_message("AI", "Hi again! 👋 Ready to sort another folder?")
        self.chat_canvas.yview_moveto(0.0)

# Run app
if __name__ == "__main__":
    root = tk.Tk()
    app = DeclutterApp(root)
    root.mainloop()
