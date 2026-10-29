import SwiftUI

/// G179 (2026-10-28) — WhatsApp on the Sources page → Messaging, drawn exactly as Messages is
/// (`MessagesRow`): the row with its mark, one status line, Refresh and Choose… (DR-40 `NeutralButton`s, DR-38 the head
/// not repeated under a source detail), and a sheet (R-HS16) with the one sentence of what is read, then one row per
/// chat — picture, name, last activity, the tick (`.switch`, mini). One addition, an existing control: "Read
/// history" per ticked chat (a `.bordered` small button, as Messages' "Read again"). No new visual pattern.

// MARK: - WhatsApp

struct WhatsAppSourceRow: View {
    let channel: SourceChannel?
    @Environment(WhatsAppWatcher.self) private var watcher
    @Environment(\.sourceDetailHeadShown) private var headShown
    @State private var showPanel = false
    @State private var note: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ChatSourceHead(origin: WhatsAppWatcher.channel, title: Copy.Chats.whatsAppTitle, headShown: headShown,
                           line: line, problem: isProblem) {
                if !watcher.tickedIds.isEmpty {
                    NeutralButton(title: Copy.Chats.refresh, size: .compact, isDisabled: watcher.status == .syncing) {
                        Task { note = (try? await watcher.syncNow()) ?? nil }
                    }
                }
                NeutralButton(title: Copy.Chats.choose, size: .compact, help: Copy.Chats.chooseHelp) { showPanel = true }
            }
            .sheet(isPresented: $showPanel) { WhatsAppPanel { showPanel = false } }
            if case .needsAccess(let error) = watcher.status { FullDiskAccessHint(error: error) }
            if channel?.connected == true {
                CapturedItemsList(channel: WhatsAppWatcher.channel)
                    .padding(.leading, headShown ? 0 : CicadaTheme.scaled(28) + CicadaTheme.spacingMD)
            }
        }
        .padding(.horizontal, headShown ? 0 : CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .settingsRow(.channel(WhatsAppWatcher.channel))
    }

    private var isProblem: Bool {
        switch watcher.status {
        case .failed, .needsAccess: true
        default: false
        }
    }

    private var line: String {
        switch watcher.status {
        case .failed(let why): return why
        case .needsAccess: return Copy.Chats.whatsAppUnreadable
        case .missing: return Copy.Chats.whatsAppMissing
        default: break
        }
        let base = watcher.tickedIds.isEmpty ? Copy.Chats.rowLineNone : Copy.Chats.rowLine(ticked: watcher.tickedIds.count)
        if let note, watcher.status != .syncing, !watcher.tickedIds.isEmpty { return "\(base) · \(note)" }
        return base
    }
}

struct WhatsAppPanel: View {
    let onDone: () -> Void
    @Environment(WhatsAppWatcher.self) private var watcher
    @State private var error: String?

    var body: some View {
        SettingsSheet(title: Copy.Chats.whatsAppTitle, onClose: onDone) {
            ChatSheetSentence(text: Copy.Chats.whatsAppWhatItReads)
            switch watcher.status {
            case .needsAccess(let fix):
                FullDiskAccessHint(error: fix) { Task { await watcher.loadList() } }
                Button(Copy.Chats.tryAgain) { Task { await watcher.loadList() } }.buttonStyle(.bordered)
            case .missing:
                Text(Copy.Chats.whatsAppMissing).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            default:
                if watcher.listing && watcher.chats.isEmpty {
                    ChatSheetLoading()
                } else if watcher.chats.isEmpty {
                    Text(Copy.Chats.noneFound).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                } else {
                    ScrollView {
                        VStack(spacing: 2) {
                            ForEach(watcher.chats) { chat in
                                ChatTickRow(name: watcher.name(of: chat), group: chat.group,
                                            last: MessagesRowText.lastActivity(chat.lastActivity),
                                            thumbnail: watcher.cards[chat.id]?.thumbnail,
                                            ticked: watcher.tickedIds.contains(chat.id),
                                            historyRead: watcher.historyIds.contains(chat.id),
                                            onTick: { on in
                                                do { try await watcher.setTicked(chat, on) }
                                                catch { self.error = WhatsAppWatcher.failureMessage(error) }
                                            },
                                            onHistory: {
                                                do { try await watcher.readHistory(chat) }
                                                catch { self.error = WhatsAppWatcher.failureMessage(error) }
                                            })
                            }
                        }
                    }
                    .frame(maxHeight: CicadaTheme.scaled(360))
                }
            }
            ChatSheetFooter(error: error, onDone: onDone)
        }
        .task { await watcher.loadList() }
    }
}

// MARK: - The shared pieces (the Messages row's, unchanged)

/// The row's head: the source's mark and name (hidden under a source detail's own head, DR-38), the status line,
/// then the trailing buttons.
struct ChatSourceHead<Trailing: View>: View {
    let origin: String
    let title: String
    let headShown: Bool
    let line: String
    let problem: Bool
    @ViewBuilder let trailing: Trailing

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if !headShown {
                LogoImage.platformTile(name: OriginIconography.logoName(for: origin) ?? "",
                                       bundleId: OriginIconography.appBundleId(for: origin),
                                       size: CicadaTheme.scaled(28),
                                       systemFallback: OriginIconography.symbol(for: origin))
            }
            VStack(alignment: .leading, spacing: 2) {
                if !headShown {
                    Text(title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                }
                Text(line)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(problem ? CicadaTheme.danger : CicadaTheme.textSecondary)
            }
            Spacer()
            trailing
        }
    }
}

struct ChatSheetSentence: View {
    let text: String
    var body: some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

struct ChatSheetLoading: View {
    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            ProgressView().controlSize(.small)
            Text(Copy.Chats.loading).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

struct ChatSheetFooter: View {
    let error: String?
    let onDone: () -> Void
    var body: some View {
        if let error {
            Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                .fixedSize(horizontal: false, vertical: true)
        }
        HStack {
            Spacer()
            Button(Copy.Chats.done, action: onDone)
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
        }
    }
}

/// One chat: its picture, name, a group tag (DR-44's one pill), last activity, "Read history" once ticked, the tick.
struct ChatTickRow: View {
    let name: String
    let group: Bool
    let last: String?
    let thumbnail: Data?
    let ticked: Bool
    let historyRead: Bool
    let onTick: (Bool) async -> Void
    let onHistory: () async -> Void
    @State private var busy = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            avatar
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if group { Tag(text: Copy.Chats.group) }
                }
                if let last {
                    Text(last).font(CicadaTheme.captionFont).monospacedDigit().foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if ticked {
                if historyRead {
                    Text(Copy.Chats.historyAsked).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                } else {
                    Button(Copy.Chats.readHistory) { run { await onHistory() } }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .help(Copy.Chats.readHistoryHelp)
                        .disabled(busy)
                }
            }
            Toggle(Copy.Chats.tickHelp, isOn: Binding(get: { ticked }, set: { on in run { await onTick(on) } }))
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
                .disabled(busy)
                .help(Copy.Chats.tickHelp)
        }
        .padding(.vertical, CicadaTheme.scaled(4))
    }

    private func run(_ body: @escaping () async -> Void) {
        busy = true
        Task {
            await body()
            busy = false
        }
    }

    @ViewBuilder
    private var avatar: some View {
        let side = CicadaTheme.scaled(28)
        Group {
            if let thumbnail, let image = NSImage(data: thumbnail) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                EntityPictureFallback(type: .person, name: name, units: 28, frame: CGSize(width: side, height: side))
            }
        }
        .frame(width: side, height: side)
        .clipShape(Circle())
    }
}
