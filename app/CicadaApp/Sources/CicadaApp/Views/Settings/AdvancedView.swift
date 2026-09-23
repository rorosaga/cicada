import AppKit
import SwiftUI

/// Settings → Advanced (G139): the backend's own status, the MCP command every
/// agent runs, where the API token lives (never the token), and which env
/// switches are set — names with plain words, never values (R-O22). Several
/// of those switches silently outrank what the app chooses
/// (`CICADA_LLM_MODE` pins the engine even on the schedule), so naming them is
/// the one way the person can tell why a choice elsewhere seems ignored.
struct AdvancedView: View {
    @Environment(Store.self) private var store
    @State private var health: HealthSnapshot?
    private let home = BackendProcess.installRoot().path

    private var overrides: [String] { store.status.value?.envOverrides ?? [] }

    private var backendLine: String {
        guard store.isConnected else { return Copy.backendNotAnswering }
        return Copy.backendLine(version: health?.version, entities: health?.entityCount, episodes: health?.episodeCount)
    }

    var body: some View {
        SettingsPage(section: .advanced) {
            SettingsGroupCard {
                SettingsRow(.backendStatus, title: Copy.backendTitle, detail: backendLine)
                SettingsDivider()
                SettingsRow(.mcpCommand, title: Copy.mcpCommandTitle, detail: Copy.mcpCommandDetail) { EmptyView() } below: {
                    CommandBox(command: "\(SnippetEscape.shell("\(home)/api/.venv/bin/python")) \(SnippetEscape.shell("\(home)/mcp/server.py"))")
                        .privacySensitive()
                }
                SettingsDivider()
                SettingsRow(.apiToken, title: Copy.apiTokenTitle,
                            detail: overrides.contains("CICADA_API_TOKEN") ? Copy.apiTokenOverridden : Copy.apiTokenDetail) {
                    Button(Copy.showInFinder) {
                        // The same home `APIClient.loadToken` reads: `CICADA_HOME`
                        // when the app was given one, else `~/.cicada`. Finder
                        // only selects the file; nothing here opens it.
                        let dir = ProcessInfo.processInfo.environment["CICADA_HOME"].map { URL(fileURLWithPath: $0) }
                            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".cicada")
                        NSWorkspace.shared.activateFileViewerSelecting([dir.appendingPathComponent("api_token")])
                    }
                }
            }
            SettingsGroupCard {
                SettingsRow(.envOverrides, title: Copy.envOverridesTitle,
                            detail: overrides.isEmpty ? Copy.envOverridesNone : nil) { EmptyView() } below: {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        ForEach(overrides, id: \.self) { name in
                            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                                Text(name).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textPrimary)
                                Text(EnvOverrideCopy.meaning(name) ?? "").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                            }
                        }
                    }
                }
            }
        }
        .task {
            await store.refresh([.status])
            health = try? await APIClient.shared.fetchHealth()
        }
    }
}
