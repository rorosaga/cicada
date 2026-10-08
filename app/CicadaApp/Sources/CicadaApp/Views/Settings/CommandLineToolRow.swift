import SwiftUI

/// G180 unit 3 — Settings → General's *Command-line tool* row (TODO ruling 21). One neutral button (DR-40), shown
/// only while there is something to link; the state in words beside it, never a promise the link can't keep; the one
/// PATH line a person would copy in a `CommandBox` (DR-19); no card of its own — it sits in Setup's card (DR-37).
struct CommandLineToolRow: View {
    let state: CommandLineToolState
    let onInstall: () -> Void

    var body: some View {
        SettingsRow(.commandLineTool, title: Copy.cliToolTitle, detail: Copy.cliToolDetail(state)) {
            switch state {
            case .notInstalled, .failed:
                NeutralButton(title: Copy.cliToolInstall, size: .compact, help: Copy.cliToolInstallHelp) { onInstall() }
            default:
                EmptyView()
            }
        } below: {
            if state == .installed(onPath: false) {
                CommandBox(command: Copy.cliToolPathLine)
            }
        }
    }
}

/// The row with this Mac's answer, re-read on each visit and after the click.
struct CommandLineToolSetting: View {
    @State private var state: CommandLineToolState = .notInstalled

    var body: some View {
        CommandLineToolRow(state: state) {
            let (target, home, onPath) = CommandLineTool.current()
            state = CommandLineTool.install(target: target, home: home, onPath: onPath)
        }
        .task {
            let (target, home, onPath) = CommandLineTool.current()
            state = CommandLineTool.state(target: target, home: home, onPath: onPath)
        }
    }
}
