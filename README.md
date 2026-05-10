# Music Pro

Desktop piano app for **Windows** with MIDI input, on-screen keyboard, chord detection, grand staff, metronome, recording/playback, and an arpeggiator. Built with **Python 3.11**, **Tkinter**, **pygame** (audio), and **mido** (MIDI).

## Requirements

- **Python 3.11** (recommended; other 3.x may work if dependencies install)
- A MIDI keyboard is optional; you can play with the **mouse** and **computer keyboard**

## Install

From a terminal in this folder:

```powershell
py -3.11 -m pip install -U pip
py -3.11 -m pip install -r requirements.txt
```

Dependencies: `pygame`, `mido`, `python-rtmidi` (for MIDI backends on Windows).

## Run

```powershell
py -3.11 .\main.py
```

If your system defaults to another Python, always use `py -3.11` so packages match.

## First-time MIDI

Use **Options → Select MIDI Input…** to pick your device. The choice is saved in `mymidi_config.json` (that file is gitignored so your settings stay local).

## Controls (summary)

| Action | How |
|--------|-----|
| Play keys | MIDI, mouse click/drag on keys, or keys **A W S E D F T G Y H U J K** |
| Key labels on keys | Hold **Shift** |
| Octave shift | **Mouse wheel** over the keyboard |
| Softer mouse notes | **Right** mouse drag |
| Glissando while dragging | Crossed notes fire while moving with button held |
| Help | **Help** menu (silent dialog) |
| Transport | **Record** ● **Stop** ■ **Play** ▶ — BPM, metronome, count-in (recording only), arpeggiator with rate |

Chord names and jazz symbols appear in the status area; the staff shows noteheads and accidentals (sharp vs flat follows chord context when possible).

## Recording

- **Record** captures MIDI note events in **beat time** (follows BPM).
- **Metronome** and **count-in** apply to **recording only**, not playback.
- **Play** replays the last take through the same synth and UI.

## License

This project is licensed under the [MIT License](LICENSE).
