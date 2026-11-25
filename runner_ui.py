import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ipa_runner import ASoftware, create_shortcut, start_legacy


BACKGROUND = '#f2f4f8'
PAPER = '#ffffff'
INK = '#142438'
MUTED = '#53647b'
ACCENT = '#2052bc'


class RunnerWindow:
    def __init__(self, root, library):
        self.root = root
        self.library = library
        self.results = queue.SimpleQueue()
        self.apps = {}
        self.busy = False
        self.asoftware_process = None
        self.notice = tk.StringVar(value='')
        self.runtime_info = tk.StringVar()
        self.name = tk.StringVar()
        self.details = tk.StringVar()
        self.app_status = tk.StringVar()
        self.root.title('TriDock（三栖）')
        self.root.geometry('940x540')
        self.root.minsize(780, 480)
        self.root.configure(bg=BACKGROUND)
        self.build()
        self.refresh()
        self.root.after(150, self.poll_tasks)
        self.root.after(2500, self.poll_status)

    def build(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TButton', font=('Segoe UI', 10), padding=(13, 8), background=PAPER, foreground=INK,
                        bordercolor='#ccd5e3', lightcolor=PAPER, darkcolor=PAPER)
        style.map('TButton', background=[('active', '#e9eef8')], foreground=[('disabled', '#8390a1')])
        style.configure('Accent.TButton', background=ACCENT, foreground=PAPER, bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.map('Accent.TButton', background=[('disabled', '#dce5f6'), ('active', '#173c8b')],
                  foreground=[('disabled', '#6e7c91')])
        style.configure('Treeview', font=('Segoe UI', 11), rowheight=43, background=PAPER,
                        fieldbackground=PAPER, foreground=INK, bordercolor='#d9e0eb')
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), padding=(9, 8), background='#e8edf6')
        style.map('Treeview', background=[('selected', '#dbe7ff')], foreground=[('selected', '#16376d')])

        header = tk.Frame(self.root, bg=INK, padx=26, pady=18)
        header.pack(fill='x')
        tk.Label(header, bg=INK, fg=PAPER, text='TriDock（三栖）', font=('Segoe UI', 23, 'bold')).pack(side='left')
        ttk.Button(header, text='运行时设置', command=self.settings).pack(side='right')
        self.import_button = ttk.Button(header, text='导入 IPA', style='Accent.TButton', command=self.import_ipa)
        self.import_button.pack(side='right', padx=(0, 10))

        body = tk.Frame(self.root, bg=BACKGROUND, padx=24, pady=20)
        body.pack(fill='both', expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        tk.Label(body, bg=BACKGROUND, fg=INK, text='应用库', font=('Segoe UI', 15, 'bold')).grid(row=0, column=0, sticky='w', pady=(0, 11))
        table = tk.Frame(body, bg=PAPER)
        table.grid(row=1, column=0, sticky='nsew', padx=(0, 16))
        self.tree = ttk.Treeview(table, columns=('name', 'arch'), show='headings', selectmode='browse', height=6)
        self.tree.heading('name', text='应用', anchor='w')
        self.tree.heading('arch', text='运行时', anchor='w')
        self.tree.column('name', minwidth=160, width=255)
        self.tree.column('arch', minwidth=110, width=130, stretch=False)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda event: self.show_selection())
        self.tree.bind('<Double-1>', self.activate_row)
        self.tree.bind('<Return>', lambda event: self.primary_action())

        panel = tk.Frame(body, bg=PAPER, padx=20, pady=18, highlightbackground='#d9e0eb', highlightthickness=1)
        panel.grid(row=1, column=1, sticky='nsew')
        panel.configure(width=270)
        for variable, font, foreground, margin in ((self.name, ('Segoe UI', 16, 'bold'), INK, 9),
                                                    (self.details, ('Segoe UI', 10), MUTED, 16),
                                                    (self.app_status, ('Segoe UI', 10), MUTED, 14)):
            tk.Label(panel, textvariable=variable, bg=PAPER, fg=foreground, font=font, justify='left',
                     wraplength=250, anchor='w').pack(fill='x', pady=(0, margin))
        self.primary = ttk.Button(panel, style='Accent.TButton', command=self.primary_action)
        self.primary.pack(fill='x', pady=(0, 8))
        self.secondary = ttk.Button(panel, command=self.secondary_action)
        self.secondary.pack(fill='x')

        footer = tk.Frame(self.root, bg=PAPER, padx=24, pady=10)
        footer.pack(side='bottom', fill='x', before=body)
        tk.Label(footer, textvariable=self.notice, bg=PAPER, fg=INK, font=('Segoe UI', 10),
                 justify='left', wraplength=470).pack(side='left')
        tk.Label(footer, textvariable=self.runtime_info, bg=PAPER, fg=MUTED,
                 font=('Segoe UI', 9)).pack(side='right', padx=(12, 0))

    def selected_app(self):
        selected = self.tree.selection()
        return self.apps.get(selected[0]) if selected else None

    def refresh(self, select=None):
        old = self.selected_app()
        self.apps = {app.bundle_id: app for app in self.library.apps()}
        if self.tree.get_children():
            self.tree.delete(*self.tree.get_children())
        for app in self.apps.values():
            self.tree.insert('', 'end', iid=app.bundle_id, values=(app.name, 'iOS 16' if app.modern else 'touchHLE'))
        preferred = select or (old.bundle_id if old else None)
        if self.apps:
            self.tree.selection_set(preferred if preferred in self.apps else next(iter(self.apps)))
        self.show_selection()

    def show_selection(self):
        touchhle = self.library.touchhle()
        legacy_ready = touchhle is not None and touchhle.is_file()
        modern_ready = False
        try:
            modern = self.library.asoftware()
            modern_ready = True
        except ValueError:
            modern = None
        self.runtime_info.set(f'touchHLE {"已连接" if legacy_ready else "未连接"}  ·  iOS 16 {"已连接" if modern_ready else "未连接"}')
        app = self.selected_app()
        self.primary.configure(state='disabled' if self.busy or not app else 'normal',
                               text='提交安装' if app and app.modern else '启动应用')
        self.secondary.configure(state='disabled' if self.busy or not app else 'normal',
                                 text='打开 iOS 窗口' if app and app.modern else '创建桌面快捷方式')
        if app is None:
            self.name.set('应用库为空')
            self.details.set('导入一个 .ipa 文件开始。')
            self.app_status.set('')
            return
        self.name.set(app.name)
        self.details.set(f'{app.bundle_id}\n版本 {app.version or "未知"}   ·   {" / ".join(app.architectures)}\n最低 iOS {app.minimum_os or "未知"}')
        if app.modern:
            try:
                status, detail = modern.status(app) if modern else ('请连接 ASoftware iOS 16', '')
            except OSError as error:
                status, detail = '读取安装状态失败', str(error)
            message = detail[:160] if status == '安装失败' and detail else '安装后在 iOS 主屏幕打开。'
            self.app_status.set(f'{status}\n{message}')
        else:
            self.app_status.set('可使用 touchHLE 启动' if legacy_ready else '请连接 touchHLE')

    def activate_row(self, event):
        if self.tree.identify_row(event.y):
            self.primary_action()

    def import_ipa(self):
        file = filedialog.askopenfilename(parent=self.root, title='选择 iOS 安装包', filetypes=[('iOS 安装包', '*.ipa')])
        if file:
            self.submit('正在导入 IPA…', lambda: self.library.add(file), self.imported)

    def imported(self, app):
        self.refresh(app.bundle_id)
        self.notice.set(f'已导入 {app.name}')

    def primary_action(self):
        app = self.selected_app()
        if self.busy or app is None:
            return
        if app.modern:
            self.submit('正在提交 IPA…', lambda: self.library.asoftware().enqueue(app), self.queued)
        else:
            self.submit(f'正在启动 {app.name}…', lambda: start_legacy(self.library, app), self.legacy_started)

    def legacy_started(self, result):
        self.monitor(*result, label='touchHLE')

    def queued(self, destination):
        if destination.parent.name == 'Installed':
            self.notice.set('该版本已安装。')
        else:
            self.notice.set('IPA 已提交。iOS 窗口运行时会处理安装。')

    def secondary_action(self):
        app = self.selected_app()
        if self.busy or app is None:
            return
        if app.modern:
            if self.asoftware_process and self.asoftware_process.poll() is None:
                self.notice.set('iOS 窗口已启动。')
                return
            log = self.library.root / 'asoftware.log'
            self.submit('正在打开 iOS 窗口…', lambda: self.library.asoftware().start(log),
                        lambda process: self.modern_started(process, log))
        else:
            self.submit('正在创建快捷方式…', lambda: create_shortcut(self.library, app),
                        lambda name: self.notice.set(f'桌面快捷方式已创建 · {name}'))

    def modern_started(self, process, log):
        self.asoftware_process = process
        self.monitor(process, log, label='iOS 16')

    def monitor(self, process, log, label):
        self.notice.set(f'{label} 已启动，正在加载。')

        def check_exit():
            code = process.poll()
            if code is None:
                self.root.after(2000, check_exit)
            elif code != 0:
                self.notice.set(f'{label} 退出（{code}）。请在数据目录查看 {log.name}。')

        self.root.after(1000, check_exit)

    def submit(self, message, work, done):
        self.busy = True
        self.import_button.configure(state='disabled')
        self.notice.set(message)
        self.show_selection()

        def worker():
            try:
                self.results.put((done, work(), None))
            except Exception as error:
                self.results.put((done, None, error))

        threading.Thread(target=worker, daemon=True).start()

    def poll_tasks(self):
        try:
            done, result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.import_button.configure(state='normal')
            if error is None:
                done(result)
            else:
                self.notice.set('操作失败')
                messagebox.showerror('TriDock（三栖）', str(error), parent=self.root)
            self.show_selection()
        self.root.after(150, self.poll_tasks)

    def poll_status(self):
        self.show_selection()
        self.root.after(2500, self.poll_status)

    def settings(self):
        panel = tk.Toplevel(self.root)
        panel.title('运行时设置')
        panel.transient(self.root)
        panel.configure(bg=PAPER, padx=24, pady=20)
        panel.resizable(False, False)
        panel.grab_set()

        def row(number, label, key, choose, initial=None):
            tk.Label(panel, text=label, bg=PAPER, fg=INK, font=('Segoe UI', 10, 'bold')).grid(row=number, column=0, sticky='w', pady=(0, 4))
            value = tk.StringVar(value=str(initial or self.library.setting(key)))
            ttk.Entry(panel, textvariable=value, width=61).grid(row=number + 1, column=0, sticky='ew', pady=(0, 15))

            def browse():
                picked = choose(parent=panel)
                if picked:
                    value.set(picked)

            ttk.Button(panel, text='浏览', command=browse).grid(row=number + 1, column=1, sticky='n', padx=(8, 0))
            return value

        legacy = row(0, 'touchHLE.exe', 'touchhle', lambda **kwargs: filedialog.askopenfilename(
            filetypes=[('touchHLE', 'touchHLE.exe')], **kwargs), self.library.touchhle())
        modern = row(2, 'ASoftware iOS 16 安装目录', 'asoftware', filedialog.askdirectory)
        work = row(4, 'iOS 16 数据目录（默认使用安装目录下的 work）', 'asoftware_work', filedialog.askdirectory)

        def save():
            try:
                legacy_path, modern_path, work_path = [value.get().strip() for value in (legacy, modern, work)]
                if legacy_path and (Path(legacy_path).name.lower() != 'touchhle.exe' or not Path(legacy_path).is_file()):
                    raise ValueError('请选择有效的 touchHLE.exe。')
                if modern_path:
                    ASoftware(Path(modern_path), work_path)
                for key, value in zip(('touchhle', 'asoftware', 'asoftware_work'), (legacy_path, modern_path, work_path)):
                    self.library.set_setting(key, Path(value).resolve() if value else '')
            except (ValueError, OSError) as error:
                messagebox.showerror('运行时设置', str(error), parent=panel)
                return
            self.show_selection()
            panel.destroy()

        links = tk.Frame(panel, bg=PAPER)
        links.grid(row=6, column=0, sticky='w')
        ttk.Button(links, text='touchHLE 下载', command=lambda: webbrowser.open('https://github.com/touchHLE/touchHLE/releases')).pack(side='left')
        ttk.Button(links, text='ASoftware iOS 下载', command=lambda: webbrowser.open('https://github.com/alpersamur3/asoft-ios/releases')).pack(side='left', padx=7)
        ttk.Button(panel, text='保存', style='Accent.TButton', command=save).grid(row=6, column=1)
        ttk.Button(panel, text='打开数据目录', command=lambda: os.startfile(self.library.root)).grid(row=7, column=0, sticky='w', pady=(10, 0))


def run(library):
    root = tk.Tk()
    RunnerWindow(root, library)
    root.mainloop()
