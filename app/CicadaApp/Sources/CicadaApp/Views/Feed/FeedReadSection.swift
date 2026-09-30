import AppKit
import SwiftUI

/// G166 — the Feed detail column's "Read" section: what an agent did with this link, in the known facts and no more
/// (`ReadWords`), and the person's controls. "Ask an agent" puts the link in the person's agent's queue and copies the
/// hand-off sentence; a login wall reads "Needs you to sign in to <site>" with "Open in browser" (the person signs in
/// themselves — the app opens the link and nothing more) and "Ask again". An agent's own words are marked as its:
/// `via` is what it said it read with, never proof. The state arrives on the row's `read` block, which moves on the
/// `reading` sync component, so a wall shows here over SSE with no bank write.
struct FeedReadSection: View {
    let item: MediaFeedItem
    @Environment(Store.self) private var store
    @State private var busy = false
    @State private var note: String?

    var body: some View {
        if ReadWords.shows(item.read), let read = item.read {
            VStack(alignment: .leading, spacing: 0) {
                SectionLabel(Copy.Reading.sectionLabel)
                    .padding(.top, CicadaTheme.scaled(24)).padding(.bottom, CicadaTheme.scaled(6))
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    // DR-7 keeps `warning` for the settings attention dot and a failed source's first clause, so a
                    // login wall is the text ladder's primary step with a neutral glyph, never a colour.
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
                        if read.status == "needs_login" {
                            Image(systemName: "person.badge.key")
                                .font(CicadaTheme.icon(.inline))
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .accessibilityHidden(true)
                        }
                        Text(ReadWords.line(read, day: ReadWords.day(read.at ?? read.askedAt)))
                            .font(CicadaTheme.detailBodyFont)
                            .foregroundStyle(read.status == "needs_login" ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if let line = ReadWords.agentNoteLine(read) {
                        Text(line)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if let via = read.via, !via.isEmpty, read.by == "agent" {
                        Text(Copy.Reading.via(via))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if let note {
                        Text(note)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    HStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(Array(ReadWords.actions(read).enumerated()), id: \.offset) { _, action in
                            button(for: action)
                        }
                    }
                }
            }
            .task(id: item.id) { note = nil }
        }
    }

    @ViewBuilder
    private func button(for action: ReadWords.Action) -> some View {
        switch action {
        case .ask:
            NeutralButton(title: Copy.Reading.ask, size: .compact, isDisabled: busy) { ask() }
        case .askAgain:
            NeutralButton(title: Copy.Reading.askAgain, size: .compact, isDisabled: busy) { ask() }
        case .unavailable(let reason):
            // DR-41 — disabled keeps its label and says why.
            NeutralButton(title: Copy.Reading.ask, size: .compact, isDisabled: true, disabledHelp: reason) {}
        case .openInBrowser:
            NeutralButton(title: Copy.Reading.openInBrowser, size: .compact, help: Copy.Reading.openInBrowserHelp) {
                if let url = ReadWords.browserURL(item.url) { NSWorkspace.shared.open(url) }
            }
        case .copyForAgent:
            NeutralButton(title: Copy.Reading.copyPrompt, size: .compact, help: Copy.Reading.copyPromptHelp) {
                Task { await copyPrompt() }
            }
        }
    }

    private func ask() {
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                let answer = try await APIClient.shared.askAgentToRead(url: item.url)
                if !answer.prompt.isEmpty { AppPasteboard.copy(answer.prompt) }
                note = Copy.Reading.askedNote
            } catch APIError.httpError(let code, let body) where code == 409 || code == 422 {
                note = ProjectWriteFailure.detail(body) ?? Copy.Reading.askFailed
            } catch {
                note = Copy.Reading.askFailed
            }
        }
    }

    private func copyPrompt() async {
        if let text = try? await APIClient.shared.fetchReadingPrompt() {
            AppPasteboard.copy(text)
            store.toast = Copy.Reading.promptCopied
        }
    }
}
