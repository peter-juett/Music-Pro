import json
import math
import tkinter as tk
import time
from array import array
from pathlib import Path
from tkinter import messagebox
from tkinter import ttk

import mido
import pygame

# --- CONFIG ---
CONFIG_PATH = Path(__file__).with_name("mymidi_config.json")
START_NOTE = 36  # C2
END_NOTE = 84    # C6
WHITE_KEY_WIDTH = 20
WHITE_KEY_HEIGHT = 200
BLACK_KEY_WIDTH = 12
BLACK_KEY_HEIGHT = 120
KEYBOARD_TOP = 0

SAMPLE_RATE = 44100
TONE_SECONDS = 3.0
POLL_MS = 16
DEFAULT_BPM = 120
KEYBOARD_MAP = {
    "a": 0,
    "w": 1,
    "s": 2,
    "e": 3,
    "d": 4,
    "f": 5,
    "t": 6,
    "g": 7,
    "y": 8,
    "h": 9,
    "u": 10,
    "j": 11,
    "k": 12,
}
NOTE_OFFSET_TO_KEY = {offset: key.upper() for key, offset in KEYBOARD_MAP.items()}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NOTE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
CHORD_PATTERNS = [
    ("Major", {0, 4, 7}),
    ("Minor", {0, 3, 7}),
    ("Diminished", {0, 3, 6}),
    ("Augmented", {0, 4, 8}),
    ("Sus2", {0, 2, 7}),
    ("Sus4", {0, 5, 7}),
    ("Maj7", {0, 4, 7, 11}),
    ("7", {0, 4, 7, 10}),
    ("Min7", {0, 3, 7, 10}),
    ("MinMaj7", {0, 3, 7, 11}),
    ("Dim7", {0, 3, 6, 9}),
    ("Half-dim7", {0, 3, 6, 10}),
]
CHORD_JAZZ_SUFFIX = {
    "Major": "",
    "Minor": "m",
    "Diminished": "dim",
    "Augmented": "aug",
    "Sus2": "sus2",
    "Sus4": "sus4",
    "Maj7": "maj7",
    "7": "7",
    "Min7": "m7",
    "MinMaj7": "m(maj7)",
    "Dim7": "dim7",
    "Half-dim7": "m7b5",
}
FLAT_FRIENDLY_ROOTS = {1, 3, 5, 6, 8, 10, 11}

WHITE = "#ffffff"
BLACK = "#000000"
BLUE = "#3296ff"
DARK = "#1e1e1e"
STAFF_BG = "#f7f7f7"
STAFF_LINE = "#333333"
STAFF_NOTE = "#111111"


def is_black(note):
    return note % 12 in [1, 3, 6, 8, 10]


def midi_to_freq(note):
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def load_app_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_app_config(config):
    try:
        CONFIG_PATH.write_text(
            json.dumps(config, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


class MidiPianoApp:
    def __init__(self, root, loading_callback=None):
        self.root = root
        self.loading_callback = loading_callback
        self.root.title("Music Pro")
        self.range_start = START_NOTE
        self.range_end = END_NOTE
        self.range_span = END_NOTE - START_NOTE

        self.white_key_count = sum(
            1 for n in range(self.range_start, self.range_end) if not is_black(n)
        )
        self.window_width = self.white_key_count * WHITE_KEY_WIDTH
        self.window_height = KEYBOARD_TOP + WHITE_KEY_HEIGHT
        self.staff_height = 180

        self.keys = [0] * 128
        self.sound_cache = {}
        self.active_channels = {}
        self.note_items = {}
        self.white_positions = {}
        self.black_positions = {}
        self.note_sources = [set() for _ in range(128)]
        self.mouse_drag_notes = {1: None, 3: None}
        self.mouse_drag_played = {1: set(), 3: set()}
        self.keyboard_pressed = {}
        self.show_labels = False
        self.current_chord_root = None
        self.port = None
        self.current_midi_device = None
        self.transport_mode = None
        self.pending_mode = None
        self.countin_start_time = None
        self.countin_total_beats = 0
        self.countin_next_beat = 0
        self.transport_start_time = None
        self.next_metronome_beat = 0
        self.recorded_events = []
        self.playback_events = []
        self.playback_index = 0
        self.arp_next_time = None
        self.arp_index = 0
        self.arp_signature = ()
        self.arp_active_channel = None
        self.arp_active_note = None
        self.app_config = load_app_config()

        self._set_loading("Initializing audio...", 5)
        self._init_audio()
        self._set_loading("Building interface...", 15)
        self._build_ui()
        self._set_loading("Generating piano sounds...", 25)
        self._build_sounds()
        self._set_loading("Detecting MIDI devices...", 92)
        self._setup_initial_midi()
        self._set_loading("Drawing keyboard...", 97)
        self.draw_keys()
        self.load_ui_settings()
        self._set_loading("Ready", 100)
        self.poll_midi()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _set_loading(self, message, percent):
        if self.loading_callback is not None:
            self.loading_callback(message, percent)

    def _init_audio(self):
        pygame.mixer.pre_init(SAMPLE_RATE, -16, 1, 512)
        pygame.mixer.init()

    def _build_ui(self):
        self.root.configure(bg=DARK)
        self.root.resizable(False, False)
        self.transport_var = tk.StringVar(value="Transport: idle")

        self.status_var = tk.StringVar(value="MIDI input: (none)")
        status = tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=DARK,
            fg="white",
            anchor="w",
            padx=8,
            pady=4,
        )
        status.pack(fill="x")
        self.playing_var = tk.StringVar(value="Notes: - | Chord: -")

        self.canvas = tk.Canvas(
            self.root,
            width=self.window_width,
            height=self.window_height,
            bg=DARK,
            highlightthickness=0,
        )
        self.canvas.pack()
        playing_status = tk.Label(
            self.root,
            textvariable=self.playing_var,
            bg=DARK,
            fg="white",
            anchor="w",
            padx=8,
            pady=6,
        )
        playing_status.pack(fill="x")

        self.staff_canvas = tk.Canvas(
            self.root,
            width=self.window_width,
            height=self.staff_height,
            bg=STAFF_BG,
            highlightthickness=0,
        )
        self.staff_canvas.pack(fill="x")
        self.draw_staff_notes()

        transport_status = tk.Label(
            self.root,
            textvariable=self.transport_var,
            bg=DARK,
            fg="white",
            anchor="w",
            padx=8,
            pady=2,
        )
        transport_status.pack(fill="x")

        controls = tk.Frame(self.root, bg=DARK, padx=8, pady=6)
        controls.pack(fill="x")

        tk.Label(controls, text="BPM", bg=DARK, fg="white").pack(side="left")
        self.bpm_var = tk.StringVar(value=str(DEFAULT_BPM))
        self.bpm_spin = tk.Spinbox(
            controls, from_=40, to=240, increment=1, width=5, textvariable=self.bpm_var
        )
        self.bpm_spin.pack(side="left", padx=(4, 12))

        self.metronome_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            controls,
            text="Metronome",
            variable=self.metronome_var,
            bg=DARK,
            fg="white",
            selectcolor=DARK,
            activebackground=DARK,
            activeforeground="white",
        ).pack(side="left")

        tk.Label(controls, text="Count-in beats", bg=DARK, fg="white").pack(side="left", padx=(12, 0))
        self.countin_var = tk.StringVar(value="4")
        tk.Spinbox(
            controls, from_=0, to=16, increment=1, width=4, textvariable=self.countin_var
        ).pack(side="left", padx=(4, 12))

        tk.Button(
            controls,
            text="●",
            fg="#d22b2b",
            width=3,
            font=("Segoe UI Symbol", 10, "bold"),
            command=self.start_record,
        ).pack(side="left", padx=(24, 0))
        tk.Button(
            controls,
            text="■",
            fg="#111111",
            width=3,
            font=("Segoe UI Symbol", 10, "bold"),
            command=self.stop_transport,
        ).pack(side="left", padx=6)
        tk.Button(
            controls,
            text="▶",
            fg="#111111",
            width=3,
            font=("Segoe UI Symbol", 10, "bold"),
            command=self.start_playback,
        ).pack(side="left")

        tk.Label(controls, text="Arp", bg=DARK, fg="white").pack(side="left", padx=(12, 4))
        self.arp_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            controls,
            text="On",
            variable=self.arp_enabled_var,
            bg=DARK,
            fg="white",
            selectcolor=DARK,
            activebackground=DARK,
            activeforeground="white",
        ).pack(side="left")
        self.arp_mode_var = tk.StringVar(value="Up")
        tk.OptionMenu(controls, self.arp_mode_var, "Up", "Down", "Up-Down").pack(side="left", padx=(6, 0))
        self.arp_rate_var = tk.StringVar(value="1/4")
        tk.OptionMenu(controls, self.arp_rate_var, "1/4", "1/8", "1/16").pack(side="left", padx=(6, 0))
        self.bpm_var.trace_add("write", self._on_setting_changed)
        self.metronome_var.trace_add("write", self._on_setting_changed)
        self.countin_var.trace_add("write", self._on_setting_changed)
        self.arp_enabled_var.trace_add("write", self._on_setting_changed)
        self.arp_mode_var.trace_add("write", self._on_setting_changed)
        self.arp_rate_var.trace_add("write", self._on_setting_changed)
        self.canvas.bind("<Button-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", lambda e: self.on_mouse_drag(e, 1))
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<Button-3>", self.on_mouse_down)
        self.canvas.bind("<B3-Motion>", lambda e: self.on_mouse_drag(e, 3))
        self.canvas.bind("<ButtonRelease-3>", self.on_mouse_up)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.focus_set()
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)
        self.root.bind("<KeyPress-Shift_L>", lambda _e: self.set_show_labels(True))
        self.root.bind("<KeyPress-Shift_R>", lambda _e: self.set_show_labels(True))
        self.root.bind("<KeyRelease-Shift_L>", lambda _e: self.set_show_labels(False))
        self.root.bind("<KeyRelease-Shift_R>", lambda _e: self.set_show_labels(False))

        menubar = tk.Menu(self.root)
        options_menu = tk.Menu(menubar, tearoff=0)
        options_menu.add_command(
            label="Select MIDI Input...",
            command=self.open_midi_selection_dialog,
        )
        menubar.add_cascade(label="Options", menu=options_menu)
        menubar.add_command(label="Help", command=self.show_help)
        self.root.config(menu=menubar)

    def _build_sounds(self):
        total_notes = 128
        for idx, note in enumerate(range(0, 128), start=1):
            if note not in self.sound_cache:
                self.sound_cache[note] = self.build_note_sound(note)
            if idx % 8 == 0 or idx == total_notes:
                progress = 25 + int((idx / total_notes) * 65)
                self._set_loading(f"Generating piano sounds... ({idx}/{total_notes})", progress)
        self.metronome_click = self.build_click_sound(freq=1760, duration_s=0.04, volume=0.35)
        self.metronome_click_downbeat = self.build_click_sound(freq=1320, duration_s=0.06, volume=0.45)

    def build_click_sound(self, freq=1400, duration_s=0.05, volume=0.3):
        frames = max(1, int(SAMPLE_RATE * duration_s))
        pcm = array("h")
        fade = max(1, int(frames * 0.2))
        for i in range(frames):
            t = i / SAMPLE_RATE
            env = max(0.0, 1.0 - (i / frames))
            if i < fade:
                env *= i / fade
            sample = math.sin(2.0 * math.pi * freq * t) * env
            pcm.append(int(sample * 32767 * volume))
        return pygame.mixer.Sound(buffer=pcm.tobytes())

    def get_bpm(self):
        try:
            value = int(self.bpm_var.get())
            return max(40, min(240, value))
        except (TypeError, ValueError):
            return DEFAULT_BPM

    def beat_now(self):
        if self.transport_start_time is None:
            return 0.0
        return (time.perf_counter() - self.transport_start_time) * self.get_bpm() / 60.0

    def play_metronome_tick(self, beat_index):
        if not self.metronome_var.get():
            return
        if self.transport_mode != "record" and self.pending_mode != "record":
            return
        if beat_index % 4 == 0:
            self.metronome_click_downbeat.play()
        else:
            self.metronome_click.play()

    def begin_with_countin(self, mode):
        self.stop_transport(clear_take=False)
        self.pending_mode = mode
        self.countin_total_beats = max(0, int(self.countin_var.get() or 0))
        if self.countin_total_beats <= 0:
            self.start_transport_mode(mode)
            return
        self.countin_start_time = time.perf_counter()
        self.countin_next_beat = 0
        self.transport_var.set(f"Transport: count-in ({self.countin_total_beats} beats)")

    def start_transport_mode(self, mode):
        self.transport_mode = mode
        self.pending_mode = None
        self.countin_start_time = None
        self.transport_start_time = time.perf_counter()
        self.next_metronome_beat = 0
        if mode == "record":
            self.recorded_events = []
            self.transport_var.set("Transport: recording")
        elif mode == "play":
            self.playback_events = sorted(self.recorded_events, key=lambda e: e["beat"])
            self.playback_index = 0
            self.transport_var.set("Transport: playing")

    def start_record(self):
        self.begin_with_countin("record")

    def start_playback(self):
        if not self.recorded_events:
            self.transport_var.set("Transport: no take recorded")
            return
        self.start_transport_mode("play")

    def stop_transport(self, clear_take=False):
        self.transport_mode = None
        self.pending_mode = None
        self.countin_start_time = None
        self.transport_start_time = None
        self.next_metronome_beat = 0
        self.playback_events = []
        self.playback_index = 0
        if self.arp_active_channel is not None:
            self.arp_active_channel.stop()
        self.arp_active_channel = None
        self.arp_active_note = None
        if clear_take:
            self.recorded_events = []
        self.transport_var.set("Transport: idle")
        self.stop_all_notes()

    def _refresh_status_text(self):
        midi_name = self.current_midi_device or "(none)"
        shift = (self.range_start - START_NOTE) // 12
        self.status_var.set(f"MIDI input: {midi_name} | Octave shift: {shift:+d}")

    def persist_settings(self):
        try:
            countin_beats = max(0, int(self.countin_var.get() or 0))
        except (TypeError, ValueError):
            countin_beats = 0
        self.app_config["midi_device"] = self.current_midi_device
        self.app_config["bpm"] = self.get_bpm()
        self.app_config["metronome_on"] = bool(self.metronome_var.get())
        self.app_config["countin_beats"] = countin_beats
        self.app_config["arp_on"] = bool(self.arp_enabled_var.get())
        self.app_config["arp_mode"] = self.arp_mode_var.get()
        self.app_config["arp_rate"] = self.arp_rate_var.get()
        save_app_config(self.app_config)

    def load_ui_settings(self):
        try:
            bpm = int(self.app_config.get("bpm", DEFAULT_BPM))
        except (TypeError, ValueError):
            bpm = DEFAULT_BPM
        self.bpm_var.set(str(max(40, min(240, bpm))))
        self.metronome_var.set(bool(self.app_config.get("metronome_on", True)))
        try:
            countin = int(self.app_config.get("countin_beats", 4))
        except (TypeError, ValueError):
            countin = 4
        self.countin_var.set(str(max(0, min(16, countin))))
        self.arp_enabled_var.set(bool(self.app_config.get("arp_on", False)))

        arp_mode = self.app_config.get("arp_mode", "Up")
        if arp_mode not in {"Up", "Down", "Up-Down"}:
            arp_mode = "Up"
        self.arp_mode_var.set(arp_mode)

        arp_rate = self.app_config.get("arp_rate", "1/4")
        if arp_rate not in {"1/4", "1/8", "1/16"}:
            arp_rate = "1/4"
        self.arp_rate_var.set(arp_rate)

        self._refresh_status_text()

    def _on_setting_changed(self, *_args):
        self.persist_settings()

    def note_name(self, note):
        octave = (note // 12) - 1
        sharp_name = NOTE_NAMES[note % 12]
        flat_name = FLAT_NOTE_NAMES[note % 12]
        if sharp_name != flat_name:
            return f"{sharp_name}{octave}/{flat_name}{octave}"
        return f"{sharp_name}{octave}"

    def accidental_symbol(self, note, use_flats=False):
        pitch_class = note % 12
        if pitch_class in {1, 3, 6, 8, 10}:
            return "♭" if use_flats else "♯"
        return None

    def staff_step_index(self, note):
        # Diatonic step index from C0. (C,D,E,F,G,A,B -> +0..+6)
        pitch_class = note % 12
        octave = (note // 12) - 1
        diatonic_offsets = {
            0: 0,   # C
            1: 0,   # C#
            2: 1,   # D
            3: 1,   # D#
            4: 2,   # E
            5: 3,   # F
            6: 3,   # F#
            7: 4,   # G
            8: 4,   # G#
            9: 5,   # A
            10: 5,  # A#
            11: 6,  # B
        }
        return octave * 7 + diatonic_offsets[pitch_class]

    def staff_y_for_note(self, note):
        # E4 is the bottom line of the treble staff (top staff).
        e4_step = 30  # 4*7 + 2
        bottom_line_y = 88
        pixels_per_step = 6
        return bottom_line_y - (self.staff_step_index(note) - e4_step) * pixels_per_step

    def draw_staff_notes(self):
        self.staff_canvas.delete("all")
        w = self.window_width
        h = self.staff_height

        # Draw treble (top) + bass (bottom) staff lines (grand staff)
        treble_lines = [40, 52, 64, 76, 88]
        bass_lines = [118, 130, 142, 154, 166]
        for y in treble_lines + bass_lines:
            self.staff_canvas.create_line(16, y, w - 16, y, fill=STAFF_LINE, width=1)

        # Clefs on the left side of the grand staff.
        self.staff_canvas.create_text(
            30,
            64,
            text="𝄞",
            fill=STAFF_LINE,
            font=("Segoe UI Symbol", 36),
        )
        self.staff_canvas.create_text(
            30,
            142,
            text="𝄢",
            fill=STAFF_LINE,
            font=("Segoe UI Symbol", 32),
        )

        # Middle C helper ledger line
        middle_c_y = self.staff_y_for_note(60)
        self.staff_canvas.create_line(w // 2 - 14, middle_c_y, w // 2 + 14, middle_c_y, fill=STAFF_LINE, width=1)

        active_notes = [n for n, vel in enumerate(self.keys) if vel > 0]
        if not active_notes:
            return

        # Stack simultaneous notes vertically at a single beat position.
        note_x = w // 2
        use_flats = (
            self.current_chord_root in FLAT_FRIENDLY_ROOTS
            if self.current_chord_root is not None
            else False
        )
        for note in sorted(active_notes):
            y = self.staff_y_for_note(note)
            self.staff_canvas.create_oval(
                note_x - 7, y - 5, note_x + 7, y + 5,
                fill=STAFF_NOTE,
                outline=STAFF_NOTE,
            )
            accidental = self.accidental_symbol(note, use_flats=use_flats)
            if accidental is not None:
                self.staff_canvas.create_text(
                    note_x - 18,
                    y,
                    text=accidental,
                    fill=STAFF_NOTE,
                    font=("Segoe UI Symbol", 10, "bold"),
                )

            # Add ledger lines for notes outside staff.
            for ledger_y in [28, 100, 178]:
                if abs(y - ledger_y) <= 3:
                    self.staff_canvas.create_line(
                        note_x - 12, ledger_y, note_x + 12, ledger_y, fill=STAFF_LINE, width=1
                    )

    def detect_chord(self, active_notes):
        if len(active_notes) < 2:
            self.current_chord_root = None
            return None

        pitch_classes = sorted({note % 12 for note in active_notes})
        pitch_class_set = set(pitch_classes)
        best = None

        for root in pitch_classes:
            intervals = {(pc - root) % 12 for pc in pitch_class_set}
            for chord_name, pattern in CHORD_PATTERNS:
                if pattern.issubset(intervals):
                    extra_count = len(intervals - pattern)
                    candidate = (extra_count, -len(pattern), root, chord_name, pattern)
                    if best is None or candidate < best:
                        best = candidate

        if best is None:
            self.current_chord_root = None
            return None
        _, _, root, chord_name, pattern = best
        self.current_chord_root = root

        bass_note = min(active_notes)
        bass_interval = (bass_note % 12 - root) % 12

        inversion_text = ""
        if bass_interval in pattern and bass_interval != 0:
            ordered = sorted(pattern)
            inversion_index = ordered.index(bass_interval)
            if inversion_index == 1:
                inversion_text = " (1st inversion)"
            elif inversion_index == 2:
                inversion_text = " (2nd inversion)"
            elif inversion_index == 3:
                inversion_text = " (3rd inversion)"
            else:
                inversion_text = f" ({inversion_index}th inversion)"

        root_name = NOTE_NAMES[root]
        jazz_suffix = CHORD_JAZZ_SUFFIX.get(chord_name, chord_name)
        jazz_symbol = f"{root_name}{jazz_suffix}"
        return f"{root_name} {chord_name}{inversion_text} [{jazz_symbol}]"

    def update_playing_status(self):
        active_notes = [note for note, velocity in enumerate(self.keys) if velocity > 0]
        if not active_notes:
            self.current_chord_root = None
            self.playing_var.set("Notes: - | Chord: -")
            self.draw_staff_notes()
            return

        note_text = ", ".join(self.note_name(note) for note in active_notes)
        chord = self.detect_chord(active_notes) or "Unknown"
        self.playing_var.set(f"Notes: {note_text} | Chord: {chord}")
        self.draw_staff_notes()

    def build_note_sound(self, note):
        freq = midi_to_freq(note)
        frames = int(SAMPLE_RATE * TONE_SECONDS)
        pcm = array("h")

        attack_samples = max(1, int(SAMPLE_RATE * 0.003))
        release_tail_samples = max(1, int(SAMPLE_RATE * 0.02))
        decay_rate = 3.5

        for i in range(frames):
            t = i / SAMPLE_RATE
            sample = (
                1.00 * math.sin(2.0 * math.pi * freq * t)
                + 0.45 * math.sin(2.0 * math.pi * (freq * 2.0) * t)
                + 0.20 * math.sin(2.0 * math.pi * (freq * 3.0) * t)
                + 0.08 * math.sin(2.0 * math.pi * (freq * 4.0) * t)
            )

            if i < attack_samples:
                envelope = i / attack_samples
            else:
                envelope = math.exp(-decay_rate * t)

            if i > frames - release_tail_samples:
                tail = max(0.0, (frames - i) / release_tail_samples)
                envelope *= tail

            pcm.append(int(sample * envelope * 32767 * 0.22))

        return pygame.mixer.Sound(buffer=pcm.tobytes())

    def _setup_initial_midi(self):
        input_names = mido.get_input_names()
        if not input_names:
            self.current_midi_device = None
            self._refresh_status_text()
            return

        saved = self.app_config.get("midi_device")
        if saved in input_names:
            self.set_midi_input(saved)
        else:
            self.set_midi_input(input_names[0])
            self.persist_settings()

    def set_midi_input(self, device_name):
        if self.port is not None:
            self.port.close()
            self.port = None

        self.port = mido.open_input(device_name)
        self.current_midi_device = device_name
        self._refresh_status_text()
        self.persist_settings()

    def open_midi_selection_dialog(self):
        input_names = mido.get_input_names()
        if not input_names:
            messagebox.showwarning("MIDI Input", "No MIDI input devices found.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Select MIDI Input")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = tk.Frame(dialog, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Available MIDI Inputs:").pack(anchor="w")

        listbox = tk.Listbox(frame, width=60, height=min(12, len(input_names)))
        listbox.pack(fill="both", expand=True, pady=(6, 8))
        for name in input_names:
            listbox.insert("end", name)

        if self.current_midi_device in input_names:
            idx = input_names.index(self.current_midi_device)
            listbox.selection_set(idx)
            listbox.see(idx)

        def apply_selection():
            selected = listbox.curselection()
            if not selected:
                messagebox.showinfo("MIDI Input", "Please select a MIDI input.")
                return
            chosen = input_names[selected[0]]
            try:
                self.set_midi_input(chosen)
            except Exception as exc:
                messagebox.showerror("MIDI Input", f"Could not open device:\n{exc}")
                return
            dialog.destroy()

        buttons = tk.Frame(frame)
        buttons.pack(fill="x")
        tk.Button(buttons, text="Use Selected", command=apply_selection).pack(
            side="right", padx=(6, 0)
        )
        tk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")

    def draw_keys(self):
        self.canvas.delete("all")
        self.note_items.clear()
        self.white_positions.clear()
        self.black_positions.clear()
        key_labels = []

        x = 0
        for note in range(self.range_start, self.range_end):
            if not is_black(note):
                fill = WHITE if self.keys[note] == 0 else BLUE
                item = self.canvas.create_rectangle(
                    x,
                    KEYBOARD_TOP,
                    x + WHITE_KEY_WIDTH,
                    KEYBOARD_TOP + WHITE_KEY_HEIGHT,
                    fill=fill,
                    outline=BLACK,
                )
                self.note_items[note] = item
                self.white_positions[note] = x
                key_labels.append((note, x, False))
                x += WHITE_KEY_WIDTH

        for note in range(self.range_start, self.range_end):
            if is_black(note):
                prev_white = note - 1
                if prev_white in self.white_positions:
                    key_x = self.white_positions[prev_white] + WHITE_KEY_WIDTH - (
                        BLACK_KEY_WIDTH // 2
                    )
                    fill = BLACK if self.keys[note] == 0 else BLUE
                    item = self.canvas.create_rectangle(
                        key_x,
                        KEYBOARD_TOP,
                        key_x + BLACK_KEY_WIDTH,
                        KEYBOARD_TOP + BLACK_KEY_HEIGHT,
                        fill=fill,
                        outline=BLACK,
                    )
                    self.note_items[note] = item
                    key_labels.append((note, key_x, True))

                    self.black_positions[note] = (
                        key_x,
                        KEYBOARD_TOP,
                        key_x + BLACK_KEY_WIDTH,
                        KEYBOARD_TOP + BLACK_KEY_HEIGHT,
                    )

        if self.show_labels:
            for note, key_x, is_black_key in key_labels:
                offset = note - self.range_start
                label = NOTE_OFFSET_TO_KEY.get(offset)
                if label is None:
                    continue

                if is_black_key:
                    text_y = KEYBOARD_TOP + BLACK_KEY_HEIGHT - 12
                    text_color = "white"
                    text_x = key_x + (BLACK_KEY_WIDTH // 2)
                    font = ("Segoe UI", 8, "bold")
                else:
                    text_y = KEYBOARD_TOP + WHITE_KEY_HEIGHT - 12
                    text_color = "#444444"
                    text_x = key_x + (WHITE_KEY_WIDTH // 2)
                    font = ("Segoe UI", 9, "bold")

                self.canvas.create_text(
                    text_x,
                    text_y,
                    text=label,
                    fill=text_color,
                    font=font,
                )

    def set_show_labels(self, visible):
        if self.show_labels == visible:
            return
        self.show_labels = visible
        self.draw_keys()

    def stop_all_notes(self):
        for note, channel in list(self.active_channels.items()):
            channel.stop()
            self.active_channels.pop(note, None)
        self.keys = [0] * 128
        self.note_sources = [set() for _ in range(128)]
        self.keyboard_pressed.clear()
        self.mouse_drag_notes = {1: None, 3: None}
        self.mouse_drag_played = {1: set(), 3: set()}
        self.draw_keys()
        self.update_playing_status()

    def show_help(self):
        self.stop_all_notes()
        dialog = tk.Toplevel(self.root)
        dialog.title("Controls")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = tk.Frame(dialog, padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        help_text = (
            "Keyboard labels:\n"
            "- Hold Shift to show A/W/S/E... key labels on piano keys.\n\n"
            "Octave shift:\n"
            "- Use mouse wheel on the keyboard to shift octave up/down.\n\n"
            "Mouse play:\n"
            "- Left drag: normal velocity gliss.\n"
            "- Right drag: softer velocity gliss."
        )
        tk.Label(frame, text=help_text, justify="left", anchor="w").pack(fill="x")
        tk.Button(frame, text="OK", width=10, command=dialog.destroy).pack(
            side="right", pady=(10, 0)
        )

        dialog.wait_window()

    def get_note_at_position(self, x, y):
        # Black keys are drawn on top, so they get priority.
        for note, (x1, y1, x2, y2) in self.black_positions.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                return note

        for note, x1 in self.white_positions.items():
            x2 = x1 + WHITE_KEY_WIDTH
            y1 = KEYBOARD_TOP
            y2 = KEYBOARD_TOP + WHITE_KEY_HEIGHT
            if x1 <= x <= x2 and y1 <= y <= y2:
                return note
        return None

    def update_note_color(self, note):
        item = self.note_items.get(note)
        if item is None:
            return
        if is_black(note):
            fill = BLACK if self.keys[note] == 0 else BLUE
        else:
            fill = WHITE if self.keys[note] == 0 else BLUE
        self.canvas.itemconfig(item, fill=fill)

    def note_on(self, note, velocity, source="midi"):
        if note < 0 or note >= 128:
            return
        was_active = bool(self.note_sources[note])
        self.note_sources[note].add(source)
        self.keys[note] = max(self.keys[note], velocity)
        self.update_note_color(note)
        self.update_playing_status()

        arp_holds_audio = (
            self.arp_enabled_var.get()
            and source not in {"playback", "arp"}
        )
        if (not arp_holds_audio) and note in self.sound_cache and (not was_active or source == "midi"):
            prev = self.active_channels.pop(note, None)
            if prev is not None:
                prev.stop()
            channel = self.sound_cache[note].play()
            if channel is not None:
                channel.set_volume(velocity / 127.0)
                self.active_channels[note] = channel
        if self.transport_mode == "record" and source != "playback":
            self.recorded_events.append({
                "beat": self.beat_now(),
                "type": "note_on",
                "note": note,
                "velocity": velocity,
            })

    def note_off(self, note, source="midi"):
        if note < 0 or note >= 128:
            return
        self.note_sources[note].discard(source)
        if self.note_sources[note]:
            return

        self.keys[note] = 0
        self.update_note_color(note)
        self.update_playing_status()

        ch = self.active_channels.pop(note, None)
        if ch is not None:
            ch.fadeout(80)
        if self.transport_mode == "record" and source != "playback":
            self.recorded_events.append({
                "beat": self.beat_now(),
                "type": "note_off",
                "note": note,
                "velocity": 0,
            })

    def trigger_tap_note(self, note, velocity, source_prefix, duration_ms=120):
        if note < self.range_start or note >= self.range_end:
            return
        tap_source = f"{source_prefix}:tap:{note}"
        self.note_on(note, velocity, source=tap_source)
        self.root.after(duration_ms, lambda n=note, s=tap_source: self.note_off(n, source=s))

    def iter_note_path(self, start_note, end_note):
        if start_note is None or end_note is None:
            return []
        if start_note == end_note:
            return [start_note]
        step = 1 if end_note > start_note else -1
        return list(range(start_note + step, end_note + step, step))

    def _velocity_for_button(self, button_num):
        return 70 if button_num == 3 else 110

    def on_mouse_down(self, event):
        button_num = event.num
        if button_num not in self.mouse_drag_notes:
            return
        note = self.get_note_at_position(event.x, event.y)
        self.mouse_drag_played[button_num] = set()
        self.mouse_drag_notes[button_num] = note
        if note is not None:
            source = f"mouse{button_num}"
            self.note_on(note, self._velocity_for_button(button_num), source=source)
            self.mouse_drag_played[button_num].add(note)

    def on_mouse_drag(self, event, button_num=None):
        if button_num is None:
            button_num = event.num
        if button_num not in self.mouse_drag_notes:
            return
        source = f"mouse{button_num}"
        note = self.get_note_at_position(event.x, event.y)
        previous = self.mouse_drag_notes[button_num]
        if note == previous:
            return

        traversed = self.iter_note_path(previous, note) if note is not None else []
        for passed_note in traversed:
            if passed_note in self.mouse_drag_played[button_num]:
                continue
            self.trigger_tap_note(
                passed_note,
                self._velocity_for_button(button_num),
                source_prefix=source,
            )
            self.mouse_drag_played[button_num].add(passed_note)

        if previous is not None:
            self.note_off(previous, source=source)
        self.mouse_drag_notes[button_num] = note
        if note is not None:
            self.note_on(note, self._velocity_for_button(button_num), source=source)

    def on_mouse_up(self, event):
        button_num = event.num
        if button_num not in self.mouse_drag_notes:
            return
        source = f"mouse{button_num}"
        note = self.mouse_drag_notes[button_num]
        if note is not None:
            self.note_off(note, source=source)
        self.mouse_drag_notes[button_num] = None
        self.mouse_drag_played[button_num] = set()

    def shift_octave(self, delta):
        if delta == 0:
            return
        candidate_start = self.range_start + (12 * delta)
        candidate_end = candidate_start + self.range_span
        if candidate_start < 0 or candidate_end > 127:
            return

        for note, channel in list(self.active_channels.items()):
            channel.fadeout(60)
            self.active_channels.pop(note, None)
        self.keys = [0] * 128
        self.note_sources = [set() for _ in range(128)]
        self.keyboard_pressed.clear()
        self.mouse_drag_notes = {1: None, 3: None}
        self.mouse_drag_played = {1: set(), 3: set()}
        self.update_playing_status()

        self.range_start = candidate_start
        self.range_end = candidate_end
        self.draw_keys()
        self._refresh_status_text()

    def on_mouse_wheel(self, event):
        self.shift_octave(1 if event.delta > 0 else -1)

    def on_key_press(self, event):
        key = event.keysym.lower()
        if key in self.keyboard_pressed:
            return
        if key not in KEYBOARD_MAP:
            return

        note = self.range_start + KEYBOARD_MAP[key]
        if note < self.range_start or note >= self.range_end:
            return

        source = f"kbd:{key}"
        self.keyboard_pressed[key] = note
        self.note_on(note, 100, source=source)

    def on_key_release(self, event):
        key = event.keysym.lower()
        note = self.keyboard_pressed.pop(key, None)
        if note is None:
            return
        source = f"kbd:{key}"
        self.note_off(note, source=source)

    def poll_midi(self):
        self.update_transport()
        if self.port is not None:
            for msg in self.port.iter_pending():
                if msg.type == "note_on":
                    if msg.velocity > 0:
                        self.note_on(msg.note, msg.velocity)
                    else:
                        self.note_off(msg.note)
                elif msg.type == "note_off":
                    self.note_off(msg.note)

        self.root.after(POLL_MS, self.poll_midi)

    def update_transport(self):
        bpm = self.get_bpm()
        now = time.perf_counter()

        if self.countin_start_time is not None:
            elapsed_beats = (now - self.countin_start_time) * bpm / 60.0
            while self.countin_next_beat <= int(elapsed_beats) and self.countin_next_beat < self.countin_total_beats:
                self.play_metronome_tick(self.countin_next_beat)
                self.countin_next_beat += 1
            if elapsed_beats >= self.countin_total_beats:
                mode = self.pending_mode
                if mode is not None:
                    self.start_transport_mode(mode)
            return

        if self.transport_mode is None or self.transport_start_time is None:
            self.update_arpeggiator(now)
            return

        current_beat = self.beat_now()
        while self.next_metronome_beat <= int(current_beat):
            self.play_metronome_tick(self.next_metronome_beat)
            self.next_metronome_beat += 1

        if self.transport_mode == "play":
            while self.playback_index < len(self.playback_events) and self.playback_events[self.playback_index]["beat"] <= current_beat:
                evt = self.playback_events[self.playback_index]
                if evt["type"] == "note_on":
                    self.note_on(evt["note"], evt["velocity"], source="playback")
                else:
                    self.note_off(evt["note"], source="playback")
                self.playback_index += 1

            if self.playback_index >= len(self.playback_events):
                # End playback once all events are dispatched.
                self.stop_transport(clear_take=False)
                return

        self.update_arpeggiator(now)

    def get_arp_notes(self):
        held = []
        for note, sources in enumerate(self.note_sources):
            if not sources:
                continue
            # Arp should follow "held" input notes, not its own generated notes.
            real_sources = [s for s in sources if not str(s).startswith("arp")]
            if real_sources:
                held.append(note)
        return held

    def build_arp_sequence(self, notes):
        if not notes:
            return []
        ordered = sorted(set(notes))
        mode = self.arp_mode_var.get()
        if mode == "Down":
            return list(reversed(ordered))
        if mode == "Up-Down":
            if len(ordered) <= 2:
                return ordered
            return ordered + ordered[-2:0:-1]
        return ordered

    def update_arpeggiator(self, now):
        if not self.arp_enabled_var.get():
            self.arp_next_time = None
            self.arp_index = 0
            self.arp_signature = ()
            if self.arp_active_channel is not None:
                self.arp_active_channel.stop()
            self.arp_active_channel = None
            self.arp_active_note = None
            return

        notes = self.get_arp_notes()
        sequence = self.build_arp_sequence(notes)
        signature = tuple(sequence)
        if signature != self.arp_signature:
            self.arp_signature = signature
            self.arp_index = 0
            self.arp_next_time = now

        if not sequence:
            if self.arp_active_channel is not None:
                self.arp_active_channel.stop()
            self.arp_active_channel = None
            self.arp_active_note = None
            return

        sec_per_beat = 60.0 / self.get_bpm()
        rate = self.arp_rate_var.get()
        if rate == "1/8":
            sec_per_step = sec_per_beat / 2.0
        elif rate == "1/16":
            sec_per_step = sec_per_beat / 4.0
        else:
            sec_per_step = sec_per_beat
        if self.arp_next_time is None:
            self.arp_next_time = now

        while now >= self.arp_next_time:
            note = sequence[self.arp_index % len(sequence)]
            if self.arp_active_channel is not None:
                self.arp_active_channel.stop()
                self.arp_active_channel = None
                self.arp_active_note = None
            channel = self.sound_cache[note].play(loops=-1)
            if channel is not None:
                channel.set_volume(0.85)
                self.arp_active_channel = channel
                self.arp_active_note = note
            self.arp_index += 1
            self.arp_next_time += sec_per_step

    def on_close(self):
        self.persist_settings()
        if self.port is not None:
            self.port.close()
        pygame.mixer.quit()
        self.root.destroy()


def main():
    root = tk.Tk()
    root.withdraw()

    loading = tk.Toplevel()
    loading.title("Loading Music Pro")
    loading.geometry("360x120")
    loading.resizable(False, False)
    loading.attributes("-topmost", True)
    loading.lift()

    loading_label_var = tk.StringVar(value="Starting...")
    ttk.Label(loading, textvariable=loading_label_var, anchor="center").pack(
        fill="x", padx=16, pady=(16, 10)
    )
    progress_var = tk.DoubleVar(value=0)
    progress = ttk.Progressbar(
        loading,
        orient="horizontal",
        mode="determinate",
        maximum=100,
        variable=progress_var,
        length=320,
    )
    progress.pack(padx=16, pady=(0, 16))

    # Force loader to render before expensive startup work begins.
    loading.update_idletasks()
    loading.update()

    def update_loading(message, percent):
        loading_label_var.set(message)
        progress_var.set(percent)
        loading.update_idletasks()
        loading.update()

    MidiPianoApp(root, loading_callback=update_loading)
    loading.destroy()
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()