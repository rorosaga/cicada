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

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            ScrollView(.horizontal, showsIndicators: false) {
                Text(command)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .textSelection(.enabled)
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .padding(.leading, CicadaTheme.spacingMD)
            }

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
                    .foregroundStyle(copied ? Color(hex: 0x3BD97A) : CicadaTheme.textSecondary)
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("Copy to clipboard")
            .padding(.top, 2)
            .padding(.trailing, CicadaTheme.spacingXS)
        }
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(Color.black.opacity(0.35))
        )
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )
        .animation(.easeInOut(duration: 0.15), value: copied)
    }
}
