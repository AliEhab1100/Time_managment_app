"""
Time Management App (Tkinter)

Features:
- Task list (add / edit / delete)
- Task fields: title, notes, due date, priority, est. duration, status
- Save / load tasks to JSON (autosave on change)
- CSV export
- Search & filter by status / priority / date
- Pomodoro-style timer (configurable work/break lengths)
- Progress bar showing completed tasks ratio
- Notifications via messagebox and system beep
"""

import json
import csv
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, date
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

APP_DATA_FILE = "tasks.json"

@dataclass
class Task:
    id: int
    title: str
    notes: str
    due: str  # ISO date YYYY-MM-DD or empty
    priority: str  # Low, Medium, High
    est_minutes: int
    status: str  # Todo, In Progress, Done


class TaskManagerApp(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.parent.title("Time Manager")
        self.pack(fill=tk.BOTH, expand=True)
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.tasks: dict[int, Task] = {}
        self._next_id = 1

        # Timer state
        self.timer_running = False
        self.timer_mode = "Work"  # Work or Break
        self.work_minutes = 25
        self.break_minutes = 5
        self.timer_seconds_left = self.work_minutes * 60
        self.timer_job = None

        self._build_ui()
        self.load_tasks()
        self._refresh_tree()
        self._update_progress()

    def _build_ui(self):
        # Top controls frame
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        add_btn = ttk.Button(top, text="Add Task", command=self._on_add)
        add_btn.pack(side=tk.LEFT)

        edit_btn = ttk.Button(top, text="Edit Task", command=self._on_edit)
        edit_btn.pack(side=tk.LEFT, padx=(6, 0))

        del_btn = ttk.Button(top, text="Delete Task", command=self._on_delete)
        del_btn.pack(side=tk.LEFT, padx=(6, 0))

        export_btn = ttk.Button(top, text="Export CSV", command=self._export_csv)
        export_btn.pack(side=tk.LEFT, padx=(12, 0))

        ttk.Label(top, text="Search:").pack(side=tk.LEFT, padx=(12, 0))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, padx=(6, 0))
        search_entry.bind("<KeyRelease>", lambda e: self._refresh_tree())

        ttk.Label(top, text="Filter:").pack(side=tk.LEFT, padx=(12, 0))
        self.filter_var = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(top, textvariable=self.filter_var, width=12, state="readonly")
        filter_combo["values"] = ("All", "Todo", "In Progress", "Done")
        filter_combo.pack(side=tk.LEFT, padx=(6, 0))
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_tree())

        # Main split: left tree, right details + timer
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

        # Treeview for tasks
        tree_frame = ttk.Frame(main)
        tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cols = ("Title", "Due", "Priority", "Est(min)", "Status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, anchor=tk.W, width=120)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_details())

        tree_scroll = ttk.Scrollbar(tree_frame, command=self.tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        # Right panel
        right = ttk.Frame(main, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        # Details
        ttk.Label(right, text="Task Details", font=(None, 12, "bold")).pack(anchor=tk.W, pady=(6,0))
        self.details_text = tk.Text(right, width=40, height=8, wrap=tk.WORD)
        self.details_text.pack(fill=tk.X, pady=(4,6))
        self.details_text.configure(state=tk.DISABLED)

        # Progress
        ttk.Label(right, text="Progress").pack(anchor=tk.W)
        self.progress = ttk.Progressbar(right, maximum=100)
        self.progress.pack(fill=tk.X, pady=(4,8))

        # Timer controls
        ttk.Label(right, text="Timer (Pomodoro)", font=(None, 12, "bold")).pack(anchor=tk.W, pady=(6,0))
        timer_frame = ttk.Frame(right)
        timer_frame.pack(fill=tk.X, pady=(4,0))

        self.timer_label = ttk.Label(timer_frame, text=self._format_time(self.timer_seconds_left), font=(None, 18))
        self.timer_label.pack()

        control_frame = ttk.Frame(right)
        control_frame.pack(pady=(8,6))

        start_btn = ttk.Button(control_frame, text="Start", command=self._start_timer)
        start_btn.grid(row=0, column=0, padx=4)
        pause_btn = ttk.Button(control_frame, text="Pause", command=self._pause_timer)
        pause_btn.grid(row=0, column=1, padx=4)
        reset_btn = ttk.Button(control_frame, text="Reset", command=self._reset_timer)
        reset_btn.grid(row=0, column=2, padx=4)

        # Timer config
        cfg_frame = ttk.Frame(right)
        cfg_frame.pack(fill=tk.X, pady=(6,0))
        ttk.Label(cfg_frame, text="Work (min):").grid(row=0, column=0, sticky=tk.W)
        self.work_var = tk.IntVar(value=self.work_minutes)
        ttk.Spinbox(cfg_frame, from_=5, to=120, textvariable=self.work_var, width=5, command=self._on_timer_config).grid(row=0, column=1)
        ttk.Label(cfg_frame, text="Break (min):").grid(row=1, column=0, sticky=tk.W)
        self.break_var = tk.IntVar(value=self.break_minutes)
        ttk.Spinbox(cfg_frame, from_=1, to=60, textvariable=self.break_var, width=5, command=self._on_timer_config).grid(row=1, column=1)

        ttk.Button(right, text="Mark Selected Done", command=self._mark_done).pack(fill=tk.X, pady=(8,0))

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def _on_timer_config(self):
        self.work_minutes = max(1, int(self.work_var.get()))
        self.break_minutes = max(1, int(self.break_var.get()))
        if not self.timer_running:
            self.timer_mode = "Work"
            self.timer_seconds_left = self.work_minutes * 60
            self._update_timer_label()

    def _format_time(self, secs: int) -> str:
        m = secs // 60
        s = secs % 60
        return f"{m:02d}:{s:02d}  ({self.timer_mode})"

    def _start_timer(self):
        if not self.timer_running:
            self.timer_running = True
            # ensure seconds align with mode
            if self.timer_seconds_left <= 0:
                self.timer_seconds_left = (self.work_minutes if self.timer_mode=="Work" else self.break_minutes) * 60
            self._schedule_timer()
            self.status_var.set("Timer running")

    def _schedule_timer(self):
        self._update_timer_label()
        if self.timer_running:
            self.timer_seconds_left -= 1
            if self.timer_seconds_left < 0:
                # switch mode
                self._on_timer_finish()
                return
            self.timer_job = self.after(1000, self._schedule_timer)

    def _pause_timer(self):
        if self.timer_running:
            self.timer_running = False
            if self.timer_job:
                self.after_cancel(self.timer_job)
                self.timer_job = None
            self.status_var.set("Timer paused")

    def _reset_timer(self):
        self.timer_running = False
        if self.timer_job:
            self.after_cancel(self.timer_job)
            self.timer_job = None
        self.timer_mode = "Work"
        self.timer_seconds_left = self.work_minutes * 60
        self._update_timer_label()
        self.status_var.set("Timer reset")

    def _update_timer_label(self):
        self.timer_label.config(text=self._format_time(self.timer_seconds_left))

    def _on_timer_finish(self):
        # beep and show message
        try:
            self.bell()
        except Exception:
            pass
        messagebox.showinfo("Timer", f"{self.timer_mode} finished!")
        # toggle
        if self.timer_mode == "Work":
            self.timer_mode = "Break"
            self.timer_seconds_left = self.break_minutes * 60
        else:
            self.timer_mode = "Work"
            self.timer_seconds_left = self.work_minutes * 60
        self.timer_running = False
        self._update_timer_label()
        self.status_var.set(f"{self.timer_mode} ready")

    # Task operations
    def _on_add(self):
        dlg = TaskDialog(self.parent)
        self.parent.wait_window(dlg.top)
        if dlg.result:
            t = dlg.result
            t.id = self._next_id
            self._next_id += 1
            self.tasks[t.id] = t
            self._save_tasks()
            self._refresh_tree()
            self._update_progress()
            self.status_var.set("Task added")

    def _on_edit(self):
        sel = self._selected_task_id()
        if sel is None:
            messagebox.showwarning("No selection", "Please select a task to edit.")
            return
        task = self.tasks[sel]
        dlg = TaskDialog(self.parent, task)
        self.parent.wait_window(dlg.top)
        if dlg.result:
            updated = dlg.result
            updated.id = sel
            self.tasks[sel] = updated
            self._save_tasks()
            self._refresh_tree()
            self._update_progress()
            self.status_var.set("Task updated")

    def _on_delete(self):
        sel = self._selected_task_id()
        if sel is None:
            messagebox.showwarning("No selection", "Please select a task to delete.")
            return
        if messagebox.askyesno("Confirm", "Delete selected task?"):
            del self.tasks[sel]
            self._save_tasks()
            self._refresh_tree()
            self._update_progress()
            self.status_var.set("Task deleted")

    def _mark_done(self):
        sel = self._selected_task_id()
        if sel is None:
            messagebox.showwarning("No selection", "Please select a task.")
            return
        self.tasks[sel].status = "Done"
        self._save_tasks()
        self._refresh_tree()
        self._update_progress()
        self.status_var.set("Task marked done")

    def _selected_task_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        item = sel[0]
        tid = int(self.tree.set(item, "#0") or 0)
        # we will also store id in iid
        try:
            return int(item)
        except Exception:
            return None

    def _show_details(self):
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        sel = self.tree.selection()
        if not sel:
            self.details_text.configure(state=tk.DISABLED)
            return
        iid = sel[0]
        tid = int(iid)
        task = self.tasks.get(tid)
        if not task:
            self.details_text.configure(state=tk.DISABLED)
            return
        s = f"Title: {task.title}\nStatus: {task.status}\nPriority: {task.priority}\nDue: {task.due or 'N/A'}\nEst (min): {task.est_minutes}\n\nNotes:\n{task.notes}"
        self.details_text.insert(tk.END, s)
        self.details_text.configure(state=tk.DISABLED)

    def _refresh_tree(self):
        q = self.search_var.get().lower().strip()
        filt = self.filter_var.get()
        for r in self.tree.get_children():
            self.tree.delete(r)
        for tid, t in sorted(self.tasks.items(), key=lambda x: (x[1].status, x[1].due or "")):
            if filt != "All" and t.status != filt:
                continue
            if q and q not in t.title.lower() and q not in t.notes.lower():
                continue
            iid = str(tid)
            self.tree.insert("", tk.END, iid, values=(t.title, t.due or "", t.priority, t.est_minutes, t.status))

    def _update_progress(self):
        if not self.tasks:
            self.progress['value'] = 0
            return
        total = len(self.tasks)
        done = sum(1 for t in self.tasks.values() if t.status == "Done")
        pct = int((done/total) * 100)
        self.progress['value'] = pct
        self.status_var.set(f"{done}/{total} tasks done ({pct}%)")

    # Persistence
    def load_tasks(self):
        if not os.path.exists(APP_DATA_FILE):
            return
        try:
            with open(APP_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                t = Task(**item)
                self.tasks[t.id] = t
                self._next_id = max(self._next_id, t.id + 1)
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load tasks: {e}")

    def _save_tasks(self):
        try:
            with open(APP_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump([asdict(t) for t in self.tasks.values()], f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save tasks: {e}")

    def _export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files","*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline='', encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["id","title","notes","due","priority","est_minutes","status"])
                for t in self.tasks.values():
                    w.writerow([t.id, t.title, t.notes, t.due, t.priority, t.est_minutes, t.status])
            messagebox.showinfo("Exported", f"Exported {len(self.tasks)} tasks to {path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))


class TaskDialog:
    def __init__(self, parent, task: Task | None = None):
        self.top = tk.Toplevel(parent)
        self.top.transient(parent)
        self.top.grab_set()
        self.result = None
        self._build(task)

    def _build(self, task: Task | None):
        self.top.title("Add Task" if task is None else "Edit Task")
        frm = ttk.Frame(self.top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Title:").grid(row=0, column=0, sticky=tk.W)
        self.title_var = tk.StringVar(value=task.title if task else "")
        ttk.Entry(frm, textvariable=self.title_var, width=40).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(frm, text="Due (YYYY-MM-DD):").grid(row=1, column=0, sticky=tk.W)
        self.due_var = tk.StringVar(value=task.due if task else "")
        ttk.Entry(frm, textvariable=self.due_var).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(frm, text="Priority:").grid(row=2, column=0, sticky=tk.W)
        self.prio_var = tk.StringVar(value=task.priority if task else "Medium")
        pr = ttk.Combobox(frm, textvariable=self.prio_var, state="readonly", values=("Low","Medium","High"))
        pr.grid(row=2, column=1, sticky=tk.W)

        ttk.Label(frm, text="Est. Minutes:").grid(row=3, column=0, sticky=tk.W)
        self.est_var = tk.IntVar(value=task.est_minutes if task else 30)
        ttk.Spinbox(frm, from_=5, to=1440, textvariable=self.est_var).grid(row=3, column=1, sticky=tk.W)

        ttk.Label(frm, text="Status:").grid(row=4, column=0, sticky=tk.W)
        self.status_var = tk.StringVar(value=task.status if task else "Todo")
        st = ttk.Combobox(frm, textvariable=self.status_var, state="readonly", values=("Todo","In Progress","Done"))
        st.grid(row=4, column=1, sticky=tk.W)

        ttk.Label(frm, text="Notes:").grid(row=5, column=0, sticky=tk.NW)
        self.notes_text = tk.Text(frm, width=40, height=8)
        self.notes_text.grid(row=5, column=1, sticky=tk.W)
        if task:
            self.notes_text.insert(tk.END, task.notes)

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT)

    def _on_ok(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("Missing", "Title is required")
            return
        due = self.due_var.get().strip()
        if due:
            try:
                # validate iso date
                datetime.strptime(due, "%Y-%m-%d")
            except Exception:
                messagebox.showwarning("Invalid", "Due date must be YYYY-MM-DD")
                return
        notes = self.notes_text.get("1.0", tk.END).strip()
        task = Task(id=0, title=title, notes=notes, due=due, priority=self.prio_var.get(), est_minutes=int(self.est_var.get()), status=self.status_var.get())
        self.result = task
        self.top.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    root.geometry('900x600')
    app = TaskManagerApp(root)
    root.mainloop()
