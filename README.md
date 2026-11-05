# Aurora

Configure the EvoFox Blaze gaming mouse from Linux. The vendor tool only runs on Windows.

Aurora talks to the mouse over its hidraw config interface. It reads and changes the settings the vendor app changes. It checks every write by reading the mouse back.

Aurora is not affiliated with EvoFox or Amkette.

## What it does

- **`aurora`** is a command line tool. `aurora get` shows the settings. `aurora set KEY=VALUE ...` changes them in one burst.
- **`aurora-tui`** is a terminal interface with tabs for the buttons, performance, backlight and profiles. It uses your terminal's own colours.

You can change:

- the polling rate (125, 250, 500 and 1000 Hz)
- the six DPI stages: value, enable, colour and the active stage
- the double click speed
- the LED effect, brightness, cycle time, symmetry and the seven LED colours
- the function of each of the eight buttons
- the active profile

## Install

Use the flake. Add it to your inputs and enable the module:

```nix
inputs.aurora = {
  url = "github:rugbedbugg/aurora";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

```nix
imports = [ inputs.aurora.nixosModules.default ];
programs.aurora.enable = true;
```

The module installs both commands and a udev rule that lets the logged in user open the mouse without root. Replug the mouse once after the rebuild.

Without the module, run `nix run github:rugbedbugg/aurora -- get`. Then give yourself access with `sudo setfacl -m u:$USER:rw /dev/hidrawN`. `aurora` prints the right node when it cannot open the mouse.

## Usage

```
aurora get
aurora get dpi polling
aurora set polling=1000 dpi.2=1800 effect=ripple button.8=rapid-fire
aurora set dpi.6=7200 --dry-run
aurora rewrite
aurora rebaseline
```

`aurora --help` lists every setting and value. `aurora-tui` has a key list under `?`. `aurora-tui --offline` opens it on a sample image and writes nothing.

## Safety

- Every write is one burst that is verified by reading the mouse back.
- A write is refused if the read of the mouse looks wrong. It is also refused if the mouse differs from the last state Aurora verified. Run `aurora rebaseline` after you change settings in another tool.
- A write is refused if it would break a rule the vendor app enforces: one button stays Left Click, one DPI stage stays enabled and the active stage stays enabled.
- If a burst fails midway, Aurora replays the previous settings.
- The last verified state lives in `$XDG_STATE_HOME/aurora`.

## Not supported yet

Macros, keyboard, media and shortcut button assignments, music lighting and button tables for profiles 1 to 3 other than button 8.

The values of most DPI indices are not known. `dpi.N=` accepts only 600, 1200, 1800, 2400, 4800, 7200 and 12800 by value.

The vendor app sets pointer speed and scroll speed through Windows. On Linux they belong in your compositor config.

`docs/protocol.txt` describes the protocol.

## Requirements

Linux with hidraw, Python 3.10 or newer and an EvoFox Blaze (USB `30fa:1440`). There are no Python dependencies.

## License

WTFPL.
