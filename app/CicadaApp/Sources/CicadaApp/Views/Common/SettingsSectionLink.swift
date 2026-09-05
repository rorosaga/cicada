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
struct SettingsSectionLink: View {
    let section: SettingsSection
    let label: String

    var body: some View {
        SettingsLink { Text(label) }
            .buttonStyle(.cicadaPlain)
            .foregroundStyle(CicadaTheme.accent)
            .simultaneousGesture(TapGesture().onEnded {
                UserDefaults.standard.set(section.rawValue, forKey: "cicada.settingsSection")
            })
            .accessibilityLabel("\(label), opens \(Copy.settings) — \(section.title)")
    }
}
