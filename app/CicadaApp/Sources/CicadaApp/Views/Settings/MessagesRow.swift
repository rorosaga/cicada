import SwiftUI

/// G179 — the Sources page → Messaging → Messages: the row, and the sheet where the person ticks the
/// conversations Cicada reads and says which one is an AI agent. Nothing is read from a conversation before its tick;
/// the list itself shows only names, last activity and counts.
struct MessagesRow: View {
    let channel: SourceChannel?
    @Environment(MessagesWatcher.self) private var watcher
    @State private var showPanel = false
    @State private var note: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoImage.platformTile(name: OriginIconography.logoName(for: "imessage") ?? "",
                                       bundleId: OriginIconography.appBundleId(for: "imessage"),
                                       size: CicadaTheme.scaled(28),
                                       systemFallback: OriginIconography.symbol(for: "imessage"))
                VStack(alignment: .leading, spacing: 2) {
                    Text(Copy.Messages.title)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(MessagesRowText.line(ticked: watcher.tickedIds.count, status: watcher.status, note: note))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(MessagesRowText.isProblem(watcher.status) ? CicadaTheme.danger
                                                                                     : CicadaTheme.textSecondary)
                }
                Spacer()
                if !watcher.tickedIds.isEmpty {
                    Button(Copy.Messages.syncNow) {
                        Task { note = (try? await watcher.syncNow()) ?? nil }
                    }
                    .buttonStyle(.bordered)
                    .disabled(watcher.status == .syncing)
                }
                Button(Copy.Messages.choose) { showPanel = true }
                    .buttonStyle(.bordered)
                    .help(Copy.Messages.chooseHelp)
            }
            // R-HS16 — a sheet, never a popover at the panel's edge.
            .sheet(isPresented: $showPanel) {
                MessagesPanel { showPanel = false }
            }
            if case .needsAccess(let error) = watcher.status {
                FullDiskAccessHint(error: error)
            }
            if channel?.connected == true {
                CapturedItemsList(channel: MessagesWatcher.channel)
                    .padding(.leading, CicadaTheme.scaled(28) + CicadaTheme.spacingMD)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .settingsRow(.channel(MessagesWatcher.channel))
    }
}

enum MessagesRowText {
    static func line(ticked: Int, status: MessagesWatcher.Status, note: String?) -> String {
        switch status {
        case .failed(let why): return why
        case .needsAccess: return Copy.Messages.unreadable
        default: break
        }
        if let note, status != .syncing { return ticked > 0 ? "\(Copy.Messages.rowLine(ticked: ticked)) · \(note)" : note }
        return ticked > 0 ? Copy.Messages.rowLine(ticked: ticked) : Copy.Messages.rowLineNone
    }

    static func isProblem(_ status: MessagesWatcher.Status) -> Bool {
        switch status {
        case .failed, .needsAccess: true
        default: false
        }
    }

    /// "Oct 14" for this year, "Oct 14, 2025" before — the list's last activity.
    static func lastActivity(_ date: Date?, now: Date = .now, calendar: Calendar = .current) -> String? {
        guard let date else { return nil }
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: now)
        return date.formatted(sameYear ? .dateTime.month(.abbreviated).day() : .dateTime.month(.abbreviated).day().year())
    }
}

/// The picker: the one sentence, the fix when Full Disk Access is missing, then one row per conversation.
struct MessagesPanel: View {
    let onDone: () -> Void
    @Environment(MessagesWatcher.self) private var watcher
    @State private var error: String?

    var body: some View {
        SettingsSheet(title: Copy.Messages.title, onClose: onDone) {
            Text(Copy.Messages.whatItReads)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(Copy.Messages.whoIsWho)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            content
            Toggle(Copy.Messages.suggestAgents, isOn: Binding(
                get: { watcher.suggestAgents },
                set: { on in Task { do { try await watcher.setSuggestAgents(on) } catch { self.error = MessagesWatcher.failureMessage(error) } } }))
                .toggleStyle(.switch)
                .controlSize(.mini)
            Text(Copy.Messages.suggestAgentsHelp)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            if !watcher.tickedIds.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Messages.readAgainHelp)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    Button(Copy.Messages.readAgain) {
                        Task {
                            do { _ = try await watcher.readAgain() } catch { self.error = MessagesWatcher.failureMessage(error) }
                        }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }
            if let error {
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            HStack {
                Text(Copy.Messages.groupsLater)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                Spacer()
                Button(Copy.Messages.done, action: onDone)
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .task { await watcher.loadList() }
    }

    @ViewBuilder
    private var content: some View {
        switch watcher.status {
        case .needsAccess(let fix):
            FullDiskAccessHint(error: fix)
            Button(Copy.Messages.tryAgain) { Task { await watcher.loadList() } }
                .buttonStyle(.bordered)
        case .missing:
            Text(Copy.Messages.noneFound).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
        default:
            if watcher.listing && watcher.conversations.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text(Copy.Messages.loading).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if watcher.conversations.isEmpty {
                Text(Copy.Messages.noneFound).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            } else {
                if !MessagesContacts.allowed {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(Copy.Messages.contactsHint)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: CicadaTheme.spacingSM)
                        Button(Copy.Messages.allowContacts) { Task { await watcher.allowContacts() } }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }
                }
                ScrollView {
                    VStack(spacing: 2) {
                        ForEach(watcher.conversations) { conversation in
                            MessagesConversationRow(conversation: conversation, onError: { error = $0 })
                        }
                    }
                }
                .frame(maxHeight: CicadaTheme.scaled(360))
            }
        }
    }
}

/// One conversation: its picture, name, last activity and count, who it is with, and the tick.
struct MessagesConversationRow: View {
    let conversation: MessagesConversation
    let onError: (String) -> Void
    @Environment(MessagesWatcher.self) private var watcher
    @State private var busy = false

    private var state: MessagesConversationState? { watcher.states[conversation.id] }
    private var name: String { watcher.name(of: conversation) }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            avatar
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(name)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let tag = MessagesConversationText.tag(state) { Tag(text: tag) }
                }
                Text(Copy.Messages.meta(last: MessagesRowText.lastActivity(conversation.lastActivity),
                                        count: conversation.messageCount))
                    .font(CicadaTheme.captionFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                if state?.asksIfAgent == true {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(Copy.Messages.askIfAgent(name))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                        Button(Copy.Messages.yesAgent) { mark(.agent) }.buttonStyle(.bordered).controlSize(.small)
                        Button(Copy.Messages.noPerson) { mark(.person) }.buttonStyle(.bordered).controlSize(.small)
                    }
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            Menu {
                Button(Copy.Messages.markAgent) { mark(.agent) }
                Button(Copy.Messages.markPerson) { mark(.person) }
                Button(Copy.Messages.markClear) { mark(.clear) }
            } label: {
                Image(systemName: "ellipsis.circle").accessibilityLabel(Copy.Messages.markMenu)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help(Copy.Messages.markMenu)
            Toggle(Copy.Messages.tickHelp, isOn: Binding(
                get: { watcher.tickedIds.contains(conversation.id) },
                set: { on in tick(on) }))
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
                .disabled(busy)
                .help(Copy.Messages.tickHelp)
        }
        .padding(.vertical, CicadaTheme.scaled(4))
    }

    @ViewBuilder
    private var avatar: some View {
        let side = CicadaTheme.scaled(28)
        Group {
            if let data = watcher.cards[conversation.id]?.thumbnail, let image = NSImage(data: data) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                EntityPictureFallback(type: .person, name: name, units: 28, frame: CGSize(width: side, height: side))
            }
        }
        .frame(width: side, height: side)
        .clipShape(Circle())
    }

    private func tick(_ on: Bool) {
        busy = true
        Task {
            defer { busy = false }
            do { try await watcher.setTicked(conversation, on) } catch { onError(MessagesWatcher.failureMessage(error)) }
        }
    }

    private func mark(_ mark: MessagesMark) {
        Task {
            do { try await watcher.mark(conversation, as: mark) } catch { onError(MessagesWatcher.failureMessage(error)) }
        }
    }
}

enum MessagesConversationText {
    /// The pill beside a name: who the person said it is, or the detectors' confident suggestion. The person's own
    /// mark (`marked`) is the answer whenever there is one — "· suggested" is only ever a detector's own answer.
    static func tag(_ state: MessagesConversationState?) -> String? {
        guard let state else { return nil }
        switch state.markedKind {
        case "agent"?: return Copy.Messages.agentTag
        case "person"?: return Copy.Messages.personTag
        default: break
        }
        switch (state.actor.kind, state.actor.decidedBy) {
        case ("agent", "person"): return Copy.Messages.agentTag
        case ("agent", "detector"): return Copy.Messages.agentTagSuggested
        case ("person", "person"): return Copy.Messages.personTag
        default: return nil
        }
    }
}
