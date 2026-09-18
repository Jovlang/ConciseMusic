#!/usr/bin/env python3
"""Simple desktop GUI for the ConciseMusic converter."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from concise_musicxml import convert, load_xml

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # The GUI remains usable through the file picker.
    DND_FILES = None
    TkinterDnD = None


SUPPORTED_SUFFIXES = {".xml", ".musicxml", ".mxl"}


def plan_outputs(sources: list[Path], output_dir: Path) -> list[tuple[Path, Path]]:
    """Choose distinct output names, even when source basenames collide."""
    used: set[str] = set()
    jobs: list[tuple[Path, Path]] = []
    for source in sources:
        stem = source.stem
        candidate = output_dir / f"{stem}.cmusic"
        number = 2
        while candidate.name.casefold() in used:
            candidate = output_dir / f"{stem}_{number}.cmusic"
            number += 1
        used.add(candidate.name.casefold())
        jobs.append((source, candidate))
    return jobs


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ConciseMusic — MusicXML Converter")
        self.root.geometry("720x520")
        self.root.minsize(580, 420)
        self.files: list[Path] = []
        self.output_dir = tk.StringVar(value=str(Path.home() / "Documents"))
        self.status = tk.StringVar(value="Add MusicXML files to begin.")
        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(outer, text="MusicXML → concise LLM format", font=("Segoe UI", 17, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            outer,
            text="Drop .xml, .musicxml, or .mxl files below, or choose them manually.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        files_frame = ttk.LabelFrame(outer, text="Input files", padding=10)
        files_frame.grid(row=2, column=0, sticky="nsew")
        files_frame.columnconfigure(0, weight=1)
        files_frame.rowconfigure(0, weight=1)

        self.file_list = tk.Listbox(files_frame, selectmode=tk.EXTENDED, activestyle="none")
        self.file_list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(files_frame, orient="vertical", command=self.file_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.file_list.configure(yscrollcommand=scrollbar.set)

        if DND_FILES is not None:
            self.file_list.drop_target_register(DND_FILES)
            self.file_list.dnd_bind("<<Drop>>", self._on_drop)
        else:
            ttk.Label(
                files_frame,
                text="Drag-and-drop needs tkinterdnd2 (pip install -r requirements.txt).",
                foreground="#a15c00",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        file_buttons = ttk.Frame(outer)
        file_buttons.grid(row=3, column=0, sticky="ew", pady=(10, 14))
        ttk.Button(file_buttons, text="Add files…", command=self._browse_files).pack(side="left")
        ttk.Button(file_buttons, text="Remove selected", command=self._remove_selected).pack(side="left", padx=8)
        ttk.Button(file_buttons, text="Clear", command=self._clear).pack(side="left")

        output = ttk.LabelFrame(outer, text="Output directory", padding=10)
        output.grid(row=4, column=0, sticky="ew")
        output.columnconfigure(0, weight=1)
        ttk.Entry(output, textvariable=self.output_dir).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(output, text="Choose…", command=self._browse_output).grid(row=0, column=1)

        bottom = ttk.Frame(outer)
        bottom.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.convert_button = ttk.Button(bottom, text="Convert", command=self._start_conversion)
        self.convert_button.grid(row=0, column=1, sticky="e")

    def _browse_files(self) -> None:
        names = filedialog.askopenfilenames(
            title="Choose MusicXML files",
            filetypes=[
                ("MusicXML files", "*.musicxml *.xml *.mxl"),
                ("All files", "*.*"),
            ],
        )
        self._add_files(Path(name) for name in names)

    def _on_drop(self, event: object) -> str:
        # splitlist correctly handles Windows paths wrapped in braces.
        names = self.root.tk.splitlist(getattr(event, "data", ""))
        self._add_files(Path(name) for name in names)
        return "break"

    def _add_files(self, paths) -> None:
        rejected = 0
        existing = {path.resolve() for path in self.files}
        for path in paths:
            path = path.expanduser()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                resolved = path.resolve()
                if resolved not in existing:
                    self.files.append(resolved)
                    existing.add(resolved)
                    self.file_list.insert(tk.END, str(resolved))
            else:
                rejected += 1
        if self.files and self.output_dir.get() == str(Path.home() / "Documents"):
            self.output_dir.set(str(self.files[0].parent))
        self.status.set(f"{len(self.files)} file(s) ready." + (f" Ignored {rejected} unsupported item(s)." if rejected else ""))

    def _remove_selected(self) -> None:
        for index in reversed(self.file_list.curselection()):
            self.file_list.delete(index)
            del self.files[index]
        self.status.set(f"{len(self.files)} file(s) ready.")

    def _clear(self) -> None:
        self.files.clear()
        self.file_list.delete(0, tk.END)
        self.status.set("Add MusicXML files to begin.")

    def _browse_output(self) -> None:
        chosen = filedialog.askdirectory(title="Choose output directory", initialdir=self.output_dir.get())
        if chosen:
            self.output_dir.set(chosen)

    def _start_conversion(self) -> None:
        if not self.files:
            messagebox.showwarning("No input files", "Add at least one MusicXML file.")
            return
        output_dir = Path(self.output_dir.get()).expanduser()
        if not output_dir.is_dir():
            messagebox.showwarning("Invalid output directory", "Choose an existing output directory.")
            return

        jobs = plan_outputs(self.files, output_dir)
        outputs = [destination for _, destination in jobs]
        existing = [path for path in outputs if path.exists()]
        if existing and not messagebox.askyesno(
            "Replace existing files",
            f"{len(existing)} output file(s) already exist. Replace them?",
        ):
            return

        self.convert_button.configure(state="disabled")
        self.status.set("Converting…")
        threading.Thread(target=self._convert_all, args=(jobs,), daemon=True).start()

    def _convert_all(self, jobs: list[tuple[Path, Path]]) -> None:
        succeeded: list[Path] = []
        failures: list[str] = []
        for source, destination in jobs:
            try:
                result = convert(load_xml(source), source.name)
                destination.write_text(result, encoding="utf-8")
                succeeded.append(destination)
            except Exception as exc:  # Keep processing the remaining selected files.
                failures.append(f"{source.name}: {exc}")
        self.root.after(0, self._conversion_finished, succeeded, failures)

    def _conversion_finished(self, succeeded: list[Path], failures: list[str]) -> None:
        self.convert_button.configure(state="normal")
        self.status.set(f"Converted {len(succeeded)} file(s)." + (f" {len(failures)} failed." if failures else ""))
        if failures:
            messagebox.showerror("Conversion finished with errors", "\n".join(failures))
        else:
            messagebox.showinfo("Conversion complete", f"Created {len(succeeded)} file(s) in:\n{succeeded[0].parent}")


def main() -> None:
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
