import SwiftUI
import AppKit

// MARK: - Copyable command box

/// A monospaced, horizontally-scrollable command/config snippet with a
/// one-click copy button. Originally introduced on the Connect page for
/// MCP registration commands; shared here so any setup/onboarding page
/// (Connect, Sync sources, …) gets the same copy-paste affordance.
struct CommandBox: View {
    let command: String
    @State private var copied = false

    /// Multi-line snippets (a JSON / TOML / YAML block) wrap; a single long
    /// command scrolls sideways. Deriving it from the content means no call
    /// site has to decide, and a config block no longer has its right-hand
    /// side clipped off inside a horizontal scroll view (G68 §1).
    static func wraps(_ command: String) -> Bool { command.contains("\n") }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            commandText

            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
                copied = true
                Task {
                    try? await Task.sleep(for: .seconds(1.5))
                    copied = false
                }
            } label: {
                Image(systemName: copied ? "checkmark" : "doc.on.doc")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(copied ? CicadaTheme.success : CicadaTheme.textSecondary)
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("Copy to clipboard")
            .accessibilityLabel(copied ? "Copied to clipboard" : "Copy command to clipboard")
            .padding(.top, 2)
            .padding(.trailing, CicadaTheme.spacingXS)
        }
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(CicadaTheme.codeBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )
        .animation(.easeInOut(duration: 0.15), value: copied)
    }

    @ViewBuilder
    private var commandText: some View {
        if Self.wraps(command) {
            snippet
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            ScrollView(.horizontal, showsIndicators: false) {
                snippet.fixedSize(horizontal: true, vertical: false)
            }
        }
    }

    private var snippet: some View {
        Text(command)
            .font(CicadaTheme.monoFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .textSelection(.enabled)
            .padding(.vertical, CicadaTheme.spacingSM)
            .padding(.leading, CicadaTheme.spacingMD)
    }
}
