import SwiftUI

/// "Open Settings, on this section" — the ONE way any surface in this app is
/// allowed to send the reader into the Settings scene (G125 v3, P5).
///
/// Two things are settled here, both of them measured rather than assumed:
///
/// 1. **A plain closure cannot open Settings on this target OS.**
///    `SidebarView.swift`'s `SettingsGearButton` docstring records the private
///    AppKit window-opening selector being *accepted and silently ignored* on
///    macOS 26 — `NSApp.sendAction` returns `true`, no window appears — which
///    gives a caller no return value to check. `SettingsEntryPointTests`
///    `.testNoPrivateSettingsSelector` fails the build on that literal
///    reappearing anywhere under `Sources/`. `SettingsLink` is a `View`, not a
///    callable action, so the entry point has to be a view too — hence this
///    wrapper instead of a helper function.
/// 2. **The section seed has exactly one writer.** `SettingsScene` restores
///    which section to show from `@AppStorage("cicada.settingsSection")`, and
///    a link that wants a specific section must seed that key BEFORE
///    `SettingsLink`'s own built-in action runs. `.simultaneousGesture` runs
///    alongside that action rather than instead of it, which is what makes the
///    ordering work. The key literal is written HERE and nowhere else
///    (`SleepQueueCardV3Tests.test_exactlyOneFileWritesTheSettingsSectionSeed`)
///    — the reader in `SettingsScene.swift` stays where it is; what must never
///    fork is the write, because a second copy-pasted writer with a typo'd key
///    fails silently by opening Settings on the wrong section.
///    The row seed (`cicada.settingsRowFocus`, G139) is written here too, in
///    the same gesture, as `<row>@<unix ms>` — the nonce lets `SettingsScene`
///    tell a new deep link from one it already consumed without ever clearing
///    the key (clearing would be a second writer).
struct SettingsSectionLink: View {
    let section: SettingsSection
    /// G139 (R-O15) — land on (scroll to and briefly wash) this row once
    /// Settings opens. Written in the SAME gesture as the section seed, in this
    /// file only, so the P5 one-writer rule covers both keys.
    var row: SettingsRowID? = nil
    let label: String
    /// G137 R-M18: an empty state's one action is the page's one prominent
    /// action — same link, same seed write, drawn through
    /// `primaryActionStyle()` instead of as accent text. Off by default, so
    /// every other caller (the Sleep page's schedule link) renders exactly
    /// as before.
    var prominent: Bool = false

    var body: some View {
        Group {
            if prominent {
                SettingsLink { Text(label).primaryActionInk() }
                    .primaryActionStyle()
            } else {
                SettingsLink { Text(label) }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accent)
            }
        }
        .simultaneousGesture(TapGesture().onEnded {
            UserDefaults.standard.set(section.rawValue, forKey: "cicada.settingsSection")
            if let row {
                UserDefaults.standard.set(SettingsRowFocusSeed.encode(row, at: Date()), forKey: "cicada.settingsRowFocus")
            }
        })
        .accessibilityLabel("\(label), opens \(Copy.settings) — \(section.title)")
    }
}
