ActualVim
----

Everything you like about using Sublime Text 3, and everything you like about typing in vim.

Actual uses an embedded [Neovim](https://neovim.io/) instance to accurately manipulate each Sublime Text buffer as though
you were editing the text directly in vim, without breaking *any* Sublime Text features (aside from multiple selection for now).

This isn't a remote terminal UI like gvim and other vim frontends.
Text modification and selections are bidirectionally synced. You can still use the entire native Sublime interface, including plugins.

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

Clone ActualVim to the path found in `Preferences -> Browse Packages...` or `sublime.packages\_path()`. Usually found here:

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

Surfacing vim's UI (like the status bar) still needs some love, but I have some good ideas for making it look beautiful (better than your terminal)
using Sublime's embedded HTML Phantom views.

Multiple selection is a work-in-progress, because it needs vim plugin support.

There are several minor bugs, and it may very rarely freeze due to the inability to tell if a command will block Neovim or not.
Some bugs are waiting on Neovim upstream, but they have been very responsive thus far.

Extremely large files might see a performance hit because the entire buffer is synced after each command. This needs to be optimized, but neovim's
msgpack rpc is fairly fast so it hasn't been a bottleneck yet.
