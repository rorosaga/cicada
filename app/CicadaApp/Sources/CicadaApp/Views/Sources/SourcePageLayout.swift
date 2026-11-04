import SwiftUI

// The standard source page (owner 2026-11-04: "we should standardize the layout for all the sources pages"; "so much
// text"). Every source's detail column is drawn by `SourcePageLayout`, four slots top to bottom:
//
//   1. **Header** — the source's real mark, its name and ONE status line (`SourceStatusLine`). Nothing else.
//   2. **Connect area** (`SourceConnectArea`) — the state the source is in (`SourceConnectState`): not connected,
//      connecting, connected, needs attention. Each state is one primary action and at most one short line. Several
//      ways in are a small set of option rows (`SourceWayIn`), each with its own icon and a switch or a button: the
//      official account, "Read through your browser", "Import a file" (the source's own mark on a file, never another
//      company's mark). A connected source with nothing to choose draws no connect area at all.
//   3. **Content** — the source's own sections (`SourceSection`): GitHub's "Your repositories" and "Starred", YouTube's
//      lists, a chat source's chats, a saved source's saves.
//   4. **Footer** (`SourcePageFooter`) — Refresh and Disconnect as quiet text buttons, last.
//
// No "Settings" heading, no paragraph anywhere. Applies DR-5 (one primary per surface), DR-9 (rings, no shadow),
// DR-20/DR-47 (section labels), DR-34 (row heights from tokens), DR-37 (a card holds a group), DR-38 (said once),
// DR-40 (four buttons), DR-52 (real marks), DR-53 (icons), DR-59 (one line), DR-74 (the head), DR-81 (no folds);
// DESIGN_RULES §9 2026-11-04.

/// Where a source's connection is — what the connect area draws.
enum SourceConnectState: Equatable {
    /// Nothing reads yet: one primary to start.
    case notConnected
    /// A sign-in or a read under way, waiting on the person or the service (a code to enter, a first read).
    case connecting
    /// On: the area draws only the ways the person may still change (a switch), else nothing.
    case connected
    /// On, but something needs the person (a lapsed sign-in, a missing permission, an install step).
    case needsAttention

    /// The state the page's status implies, for sources with no flow of their own.
    static func of(_ status: SourcePageStatus) -> SourceConnectState {
        switch status {
        case .connected, .checked: .connected
        case .syncing: .connecting
        case .needsYou: .needsAttention
        case .off, .notInstalled: .notConnected
        }
    }
}

/// The connect area's one primary action (DR-5, DR-40: at most one per surface).
struct SourcePrimaryAction {
    let title: String
    var systemImage: String? = nil
    var help: String? = nil
    var isDisabled = false
    let action: () -> Void
}

/// One way in to a source: an icon, a name, and a switch or a button.
struct SourceWayIn: Identifiable {
    enum Icon: Equatable {
        /// The source's own mark (an `OriginIconography` key) — the official account connection.
        case mark(String)
        /// An SF Symbol (the browser reader's globe).
        case symbol(String)
        /// The source's own mark on a file — "Import a file" (never another company's mark).
        case file(String)
    }

    enum Control {
        /// A switch, its value and what flipping it does.
        case toggle(Bool, (Bool) -> Void)
        /// A neutral button's words and its action.
        case button(String, () -> Void)
    }

    let id: String
    let icon: Icon
    let title: String
    let control: Control
    var help: String? = nil
    var isDisabled = false

    /// "Read through your browser" — the browser-harness agent's per-site switch.
    static func browser(on: Bool, help: String? = nil, set: @escaping (Bool) -> Void) -> SourceWayIn {
        SourceWayIn(id: "browser", icon: .symbol("globe"), title: Copy.SourceLayout.readInBrowser,
                    control: .toggle(on, set), help: help ?? Copy.SourceLayout.readInBrowserHelp)
    }

    /// "Import a file" — the source's own mark on a file icon, opening its import.
    static func importFile(origin: String, title: String = Copy.SourceLayout.importFile,
                           help: String? = nil, action: @escaping () -> Void) -> SourceWayIn {
        SourceWayIn(id: "file", icon: .file(origin), title: title,
                    control: .button(Copy.SourceLayout.choose, action), help: help)
    }
}

/// A footer action: Refresh, Disconnect — quiet text buttons; a destructive one asks first.
struct SourceFooterAction: Identifiable {
    let id: String
    let title: String
    var help: String? = nil
    var isDisabled = false
    /// Set for a destructive action: the confirmation's title, its destructive button's words, and one line.
    var confirm: (title: String, button: String, message: String?)? = nil
    let action: () -> Void

    static func refresh(isDisabled: Bool = false, action: @escaping () -> Void) -> SourceFooterAction {
        SourceFooterAction(id: "refresh", title: Copy.SourceLayout.refresh, help: Copy.SourceLayout.refreshHelp,
                           isDisabled: isDisabled, action: action)
    }

    static func disconnect(_ source: String, message: String? = nil, isDisabled: Bool = false,
                           action: @escaping () -> Void) -> SourceFooterAction {
        SourceFooterAction(id: "disconnect", title: Copy.SourceLayout.disconnect, isDisabled: isDisabled,
                           confirm: (Copy.SourceLayout.disconnectTitle(source), Copy.SourceLayout.disconnect,
                                     message ?? Copy.SourceLayout.disconnectKeeps),
                           action: action)
    }
}

// MARK: - The layout

/// The one source page. The header is drawn from `title`, `origin` and `status`; the three slots are the caller's.
/// `drilled` replaces the connect area, the content and the footer with one list opened in the column's place
/// (DR-81's "All N", a chat's conversations), "‹ <source>" and Esc returning.
struct SourcePageLayout<Connect: View, Content: View, Footer: View>: View {
    let title: String
    /// The source's `OriginIconography` key — its real mark (DR-52).
    let origin: String
    let status: SourcePageStatus
    /// What the status words measure, on hover only (never a standing sentence).
    var statusHelp: String? = nil
    var backLabel: String? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void
    @ViewBuilder var connect: () -> Connect
    @ViewBuilder var content: () -> Content
    @ViewBuilder var footer: () -> Footer

    /// The status line sits under the name: the mark tile (36) and the head's gap.
    static var statusIndent: CGFloat { CicadaTheme.scaled(36) + CicadaTheme.spacingMD }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                DetailHeader(title: title, backLabel: backLabel, onShowList: onShowList,
                             closeHelp: Copy.Lists.closeSource,
                             closeShortcut: KeyboardShortcut("[", modifiers: .command), onClose: onClose) {
                    SourceLogoTile(origin: origin)
                }
                SourceStatusLine(status: status, help: statusHelp)
                    .padding(.leading, Self.statusIndent)
                    .padding(.top, -CicadaTheme.spacingMD)
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingLG)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                    connect()
                    content()
                    footer()
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth + 64), maxHeight: .infinity,
               alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .top)
    }
}

// MARK: - The connect area

/// The connect area: one primary, at most one short line, then the ways in as option rows. `extra` holds a step's own
/// body when it has one (a code to enter, a phone number) between the line and the ways. Draws nothing when it has
/// nothing (DR-81).
struct SourceConnectArea<Extra: View>: View {
    var primary: SourcePrimaryAction? = nil
    /// One short line, in tertiary ink, never wrapped — its full words on hover.
    var line: String? = nil
    /// The line reads as the one thing to fix (a needs-attention state): warning ink (DR-7).
    var lineIsAttention = false
    var ways: [SourceWayIn] = []
    @ViewBuilder var extra: () -> Extra

    var body: some View {
        if primary != nil || line != nil || !ways.isEmpty || Extra.self != EmptyView.self {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                if primary != nil || line != nil {
                    HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                        if let primary {
                            PrimaryActionButton(title: primary.title, systemImage: primary.systemImage,
                                                action: primary.action)
                                .disabled(primary.isDisabled)
                                .help(primary.help ?? primary.title)
                                .fixedSize()
                        }
                        if let line { SourceConnectLine(text: line, isAttention: lineIsAttention) }
                        Spacer(minLength: 0)
                    }
                }
                extra()
                if !ways.isEmpty { SourceWaysList(ways: ways) }
            }
        }
    }
}

extension SourceConnectArea where Extra == EmptyView {
    init(primary: SourcePrimaryAction? = nil, line: String? = nil, lineIsAttention: Bool = false,
         ways: [SourceWayIn] = []) {
        self.init(primary: primary, line: line, lineIsAttention: lineIsAttention, ways: ways, extra: { EmptyView() })
    }
}

/// The connect area's one line: meta size, one line, the whole of it on hover (DR-59).
struct SourceConnectLine: View {
    let text: String
    var isAttention = false

    var body: some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(isAttention ? CicadaTheme.warning : CicadaTheme.textTertiary)
            .lineLimit(1)
            .truncationMode(.tail)
            .help(text)
    }
}

/// The ways in, one 36 pt option row each (DR-34), grouped on one ringed block (DR-9, DR-37: the block holds a group).
struct SourceWaysList: View {
    let ways: [SourceWayIn]

    var body: some View {
        VStack(spacing: 0) {
            ForEach(ways) { SourceWayRow(way: $0) }
        }
        .padding(.vertical, CicadaTheme.spacingXS)
        .glassCard(cornerRadius: CicadaTheme.cornerRadius)
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
    }
}

struct SourceWayRow: View {
    let way: SourceWayIn

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            SourceWayIcon(icon: way.icon)
            Text(way.title)
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
            Spacer(minLength: CicadaTheme.spacingSM)
            switch way.control {
            case .toggle(let on, let set):
                Toggle(isOn: Binding(get: { on }, set: set)) { EmptyView() }
                    .toggleStyle(.switch)
                    .controlSize(.mini)
                    .labelsHidden()
                    .disabled(way.isDisabled)
                    .accessibilityLabel(way.title)
            case .button(let title, let action):
                NeutralButton(title: title, size: .compact, isDisabled: way.isDisabled, help: way.help ?? way.title,
                              action: action)
                    .accessibilityLabel("\(way.title), \(title)")
            }
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
        .padding(.horizontal, CicadaTheme.scaled(12))
        .help(way.help ?? way.title)
    }
}

/// A way's icon at the list glyph's size (DR-53): the source's real mark (DR-52), a symbol, or the source's mark on a
/// file — the import's icon is the source's own, never other companies' marks.
struct SourceWayIcon: View {
    let icon: SourceWayIn.Icon

    var body: some View {
        let side = CicadaTheme.iconPoints(.titlebar)
        Group {
            switch icon {
            case .mark(let origin):
                OriginMark(origin: origin, size: side)
            case .symbol(let name):
                Image(systemName: name)
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textSecondary)
            case .file(let origin):
                ZStack(alignment: .bottomTrailing) {
                    Image(systemName: "doc")
                        .font(CicadaTheme.font(size: 15))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: side, height: side)
                    OriginMark(origin: origin, size: CicadaTheme.scaled(10))
                        .offset(x: CicadaTheme.scaled(3), y: CicadaTheme.scaled(2))
                }
            }
        }
        .frame(width: side, height: side)
        .accessibilityHidden(true)
    }
}

// MARK: - Content

/// One of a source's own sections: its label (DR-47) with how many it holds as meta, then its rows. A section with
/// nothing in it is not drawn by its caller (DR-81).
struct SourceSection<Rows: View>: View {
    let title: String
    var count: String? = nil
    @ViewBuilder var rows: () -> Rows

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                SectionLabel(title)
                if let count {
                    Text(count)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Spacer(minLength: 0)
            }
            .frame(minHeight: CicadaTheme.scaled(24), alignment: .leading)
            rows()
        }
    }
}

// MARK: - Footer

/// Refresh and Disconnect, quiet and last: text buttons (DR-40) flush with the column's edge; a destructive one asks
/// first in a confirmation whose button carries the danger role. `note` is what the last action said, one line.
struct SourcePageFooter: View {
    var actions: [SourceFooterAction]
    var note: String? = nil

    @State private var confirming: SourceFooterAction.ID?

    var body: some View {
        if !actions.isEmpty || note != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let note {
                    Text(note)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(2)
                        .help(note)
                }
                HStack(spacing: CicadaTheme.spacingXS) {
                    ForEach(actions) { item in
                        TextButton(title: item.title, help: item.help ?? item.title) {
                            if item.confirm != nil { confirming = item.id } else { item.action() }
                        }
                        .disabled(item.isDisabled)
                        .opacity(item.isDisabled ? NeutralButton.disabledOpacity : 1)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.leading, -TextButton.inset(inline: false))
            }
            .confirmationDialog(confirmed?.confirm?.title ?? "",
                                isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } }),
                                presenting: confirmed) { item in
                Button(item.confirm?.button ?? item.title, role: .destructive) { item.action() }
                Button(Copy.cancelAction, role: .cancel) {}
            } message: { item in
                if let message = item.confirm?.message { Text(message) }
            }
        }
    }

    private var confirmed: SourceFooterAction? { actions.first { $0.id == confirming } }
}
