import SwiftUI
import AppKit

// MARK: - Copyable command box

/// A monospaced, wrapping command/config snippet with a one-click copy
/// button. Originally introduced on the Connect page for MCP registration
/// commands; shared here so any setup/onboarding page (Connect, Sync
/// sources, …) gets the same copy-paste affordance.
///
/// Every snippet — a single-line command or a multi-line JSON/TOML/YAML
/// block — wraps fully to the box's width; nothing is ever clipped off past
/// the visible edge (G68 §1, round 2: single-line commands used to scroll
/// sideways inside a fixed-width box instead of wrapping, clipping mid-word).
struct CommandBox: View {
    let command: String
    @State private var copied = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            snippet
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

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
            .buttonStyle(.cicadaPlain)
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

    private var snippet: some View {
        Text(command)
            .font(CicadaTheme.monoFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .textSelection(.enabled)
            .padding(.vertical, CicadaTheme.spacingSM)
            .padding(.leading, CicadaTheme.spacingMD)
    }
}
