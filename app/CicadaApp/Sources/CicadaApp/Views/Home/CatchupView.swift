import SwiftUI

/// Ruling 48 (8) — the worm's head as Cicada's face in the catch-up chat (owner 2026-10-28: "the questioning head
/// moving, and when I'm talking in the chat with him he reacts"). The menu bar's own 18 × 18 sprite, its frames played
/// from the sheet on the shared sprite clock (ruling 18 — the sheet's timings, inside `CicadaMotion`'s sprite caps; no
/// new frames were needed): asking is *curious* (the question mark), listening while the person types is *reading*,
/// waiting on an answer is *digesting*, a noted answer is *happy*, the end of the chat *awake*. The code-drawn badge and
/// stage dots of the menu bar are left off — this is a face, not a count. A mood change swaps the clip in one frame,
/// never through `withAnimation`, so a key that changes it never animates (DR-60); Reduce Motion and Low Power hold
/// the clip's key frame (`SpriteLayerView`, DR-66). DR-13 is unchanged: a face beside its words, never art behind data.
struct WormFace: View {
    let mood: CatchupSession.Mood
    var size: CGFloat = 32

    @AppStorage(MascotPreference.defaultsKey) private var mascotRaw = MascotRegistry.bookworm.id

    static func tag(_ mood: CatchupSession.Mood) -> String {
        switch mood {
        case .asking: "curious"
        case .listening: "reading"
        case .thinking: "digesting"
        case .pleased: "happy"
        case .idle: "awake"
        }
    }

    var body: some View {
        let sheet = SpriteSheets.sheet(named: MascotRegistry.resolve(mascotRaw).menuBarSheet)
        let canvas = sheet?.frameSize ?? BookwormArt.smallFrame
        let scale = max(1, (CicadaTheme.scaled(size) / canvas.height).rounded())
        SpriteLayerView(clip: sheet?.clip(Self.tag(mood)) ?? sheet?.clip("awake"), sheet: sheet, pixelScale: scale,
                        canvasSize: canvas)
            .frame(width: canvas.width * scale, height: canvas.height * scale)
            .accessibilityHidden(true)
    }
}

/// Ruling 48 (8), mock `08-catchup` — *Catch me up* in place on Home, read as a chat (the 2026-10-19 Reader ruling:
/// Cicada on the left, the person on the right). One tap still answers (DR-42, with Undo); the person's own words go
/// to one turn on their chosen engine (`CatchupSession`). Esc, × and *Stop for now* leave it; nothing here is a
/// trigger for Sleep.
struct CatchupView: View {
    @Bindable var session: CatchupSession
    let onClose: () -> Void
    let openPage: (String) -> Void
    let openQuestion: (String) -> Void

    @Environment(Store.self) private var store
    @FocusState private var composing: Bool

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                        ForEach(session.lines) { line in
                            lineView(line).id(line.id)
                        }
                        if session.waiting {
                            Text(Copy.Catchup.thinking)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .padding(.leading, faceGutter)
                        }
                        answers
                        Color.clear.frame(height: 1).id(Self.bottom)
                    }
                    .frame(maxWidth: CicadaTheme.scaled(HomeLayout.columnWidth), alignment: .leading)
                    .padding(.horizontal, CicadaTheme.spacingGutter)
                    .padding(.vertical, CicadaTheme.spacingLG)
                    .frame(maxWidth: .infinity)
                }
                .softTopScrollEdge()
                // A new line scrolls into view in one frame: typing and ⏎ drive it, and a key never animates (DR-60).
                .onChange(of: session.lines.count) { _, _ in proxy.scrollTo(Self.bottom, anchor: .bottom) }
                .onChange(of: session.waiting) { _, _ in proxy.scrollTo(Self.bottom, anchor: .bottom) }
            }
            composer
        }
        .background(CicadaTheme.bgBase)
        .onAppear {
            session.start()
            composing = true
        }
        .onExitCommand { onClose() }
    }

    private static let bottom = "catchup.bottom"
    private var faceGutter: CGFloat { CicadaTheme.scaled(32) + CicadaTheme.spacingSM }

    // MARK: Header — "Home · Catching up · 3 of 6", Stop for now, ×

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Text(session.finished || session.total == 0 ? Copy.Catchup.eyebrow
                 : "\(Copy.Catchup.eyebrow) · \(Copy.Catchup.position(session.position, of: session.total))")
                .font(CicadaTheme.metaMediumFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: CicadaTheme.spacingSM)
            if !session.finished {
                TextButton(title: Copy.Catchup.stop) { session.stop() }
            }
            IconButton(systemName: "xmark", help: Copy.Catchup.closeHelp, action: onClose)
        }
        .frame(minHeight: CicadaTheme.scaled(EyebrowRow<EmptyView>.minHeight))
        .padding(.top, CicadaTheme.scaled(EyebrowRow<EmptyView>.topPadding))
        .padding(.horizontal, CicadaTheme.spacingGutter)
    }

    // MARK: Lines

    @ViewBuilder
    private func lineView(_ line: CatchupLine) -> some View {
        switch line.kind {
        case .cicada(let text, let itemId):
            cicada(text, itemId: itemId, live: line.id == lastCicadaId)
        case .you(let text), .tap(let text, _):
            VStack(alignment: .trailing, spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.Catchup.you)
                Text(text)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.scaled(10))
                    .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgSelected))
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.leading, CicadaTheme.scaled(120))
        case .noted(let text, let heldId):
            HStack(spacing: CicadaTheme.scaled(6)) {
                Image(systemName: "checkmark")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
                Text(text)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                if session.undoableId == heldId {
                    Text(Copy.Inbox.dot).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    InlineLink(title: Copy.Catchup.undo) { session.undo(heldId) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        case .aside(let text):
            Text(text)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.leading, faceGutter)
        }
    }

    private var lastCicadaId: UUID? {
        session.lines.last { if case .cicada = $0.kind { return true } else { return false } }?.id
    }

    /// Cicada's words beside its face: the live worm on the latest line only (one sprite playing, not a column of
    /// them), the speaker's name over the rest. A question's page sits under it as a link.
    private func cicada(_ text: String, itemId: String?, live: Bool) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Group {
                if live {
                    WormFace(mood: session.mood)
                } else {
                    Color.clear
                }
            }
            .frame(width: CicadaTheme.scaled(32), height: CicadaTheme.scaled(32))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.Catchup.speaker)
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text(text)
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                    if let itemId, let item = store.inbox.value?.first(where: { $0.id == itemId }),
                       !item.entityId.isEmpty {
                        HStack(spacing: CicadaTheme.scaled(6)) {
                            EntityPicture(id: item.entityId, name: item.displayName,
                                          type: item.entityType.flatMap(EntityType.init(rawValue:)) ?? .concept,
                                          size: 18)
                            InlineLink(title: item.displayName, help: Copy.Catchup.openPage(item.displayName)) {
                                openPage(item.entityId)
                            }
                        }
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.vertical, CicadaTheme.scaled(10))
                .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
                .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
            }
            .frame(maxWidth: CicadaTheme.scaled(560), alignment: .leading)
            Spacer(minLength: 0)
        }
    }

    // MARK: The answers under the question (DR-42)

    @ViewBuilder
    private var answers: some View {
        if !session.waiting, !session.finished {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                // Agent proposes, the person disposes: a reading from their words waits for this tap.
                if let pending = session.confirmation {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(pending.label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        NeutralButton(title: Copy.Catchup.yes, size: .compact) { session.confirm() }
                        TextButton(title: Copy.Catchup.notQuite, help: Copy.Catchup.notQuiteHelp) {
                            session.notQuite()
                            composing = true
                        }
                    }
                }
                if let item = session.current {
                    let chips = session.chips
                    FlowLayout(spacing: CicadaTheme.spacingSM) {
                        ForEach(chips) { chip in
                            switch chip.role {
                            case .answer:
                                NeutralButton(title: chip.label, size: .compact) { session.tap(chip) }
                            case .notNow, .skip:
                                TextButton(title: chip.label) { session.tap(chip) }
                            }
                        }
                        if chips.allSatisfy({ $0.role != .answer }), FocusCardVariant.of(item) != .freeText {
                            TextButton(title: Copy.Catchup.openFull) { openQuestion(item.id) }
                        }
                    }
                }
            }
            .padding(.leading, faceGutter)
        }
    }

    // MARK: The composer — the person's own words

    private var composer: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(Copy.Catchup.composer, text: $session.draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(CicadaTheme.detailBodyFont)
                .lineLimit(1...4)
                .focused($composing)
                .disabled(session.finished || session.current == nil)
                .onSubmit { Task { await session.send() } }
            KeyHint("⏎")
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.scaled(10))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .frame(maxWidth: CicadaTheme.scaled(HomeLayout.columnWidth))
        .padding(.horizontal, CicadaTheme.spacingGutter)
        .padding(.bottom, CicadaTheme.spacingLG)
        .padding(.top, CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity)
    }
}
