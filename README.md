ActualVim
----

Everything you like about using Sublime Text 3, and everything you like about typing in vim.

Actual uses an embedded [Neovim](https://neovim.io/) instance to accurately manipulate each Sublime Text buffer as though
you were editing the text directly in vim, while the Sublime Text interface, features, and plugins continue to work (see end of README for caveats).

This isn't a remote terminal UI like gvim and other vim frontends.
Text modification and selections are bidirectionally synced into the actual Sublime Text UI.

Why?
----

Sublime looks way better than your terminal and has a rich plugin ecosystem.

Other Sublime vim emulation plugins, including the built-in Vintage, are only rough approximations of the functionality of vim itself.
They are missing features or behave differently than the real thing.

With ActualVim, you can use your own vimrc, plugins, and any real vim motions/commands, because it *is* vim behind the scenes,
and bidirectional sync means Sublime Text and the native OS interface still works too.

Usage
----

This plugin requires [Neovim to be installed](https://neovim.io/), but should otherwise work on all Sublime Text 3 platforms (tested primarily on Windows and macOS).

Clone ActualVim to the path found in `Preferences -> Browse Packages...` or `sublime.packages_path()`. Usually found here:

- macOS: `~/Library/Application Support/Sublime Text 3/Packages/`
- Linux: `~/.config/sublime-text-3/Packages/`
- Windows: `%APPDATA%/Sublime Text 3/Packages/`

You can set the Neovim path by opening `Preferences: ActualVim Settings` using the command palette
(`cmd+shift+p` or `ctrl+shift+p`) or via `Preferences -> Package Settings -> ActualVim Settings`.

ActualVim launches a single Neovim embedded instance and multiplexes each Sublime view into a separate buffer.

If the plugin doesn't work (a horizontal underline cursor appears when ActualVim kicks in), check the Sublime Text console for errors and make sure you set the Neovim path.
Barring that, file an issue.

Misc
----

On OS X 10.7+, you should do `defaults write com.sublimetext.3 ApplePressAndHoldEnabled -bool false` to enable key repeat.

You can run `ActualVim: Disable` or `ActualVim: Enable` via the command pallete to toggle the input mode without losing vim state.

Caveats
----

Currently broken Sublime Features:

- Multiple Selection (#8).
- Auto-popups while typing, like completion (#57) and snippet suggestions (#94).
- Sublime's undo isn't coalesced properly while in vim mode (it's one character at a time: #44).

Surfacing vim's UI (like the status bar) still needs some love, but I have some good ideas for making it look beautiful (better than your terminal)
using Sublime's embedded HTML Phantom views.

Extremely large files will see a performance hit until neovim supports change deltas. The `large_file_disable` command mitigates this by disabling
ActualVim for larger files (with configurable cutoff).
