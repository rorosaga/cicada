import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Track I part b (design §4.1.3–§4.1.6, W4–W11) — the Welcome's checklist: what
/// is really on this Mac, each row ticked or not, and the ticks are the consent.
/// It renders and records the person's answers into the Welcome's own state
/// (the bindings); it runs nothing. Nothing is read before the tick (R-IB12):
/// detection is part a's `LocalInventory` unchanged, so a browser row carries
/// no bookmark count and an agent row only a read-only wiring status. Every
/// write waits for Start, which runs `SetupRunner` over exactly the ticked set.
struct WelcomeChecklist: View {
    @Binding var ticked: Set<FoundItemID>
    @Binding var touched: Set<FoundItemID>
    @Binding var allowRequested: Set<FoundItemID>
    @Binding var droppedTicked: Set<String>
    @Binding var pick: String?
    let revealed: Bool
    /// The window's one drop target is hovered (R-IB8): the chat zone lights up
    /// in the meadow wash — a wash, never a data encoding (W10, R-M2).
    let dropTargeted: Bool

    @Environment(LocalInventory.self) private var inventory
    @Environment(IntakeRouter.self) private var intake
    @Environment(ExportWaitStore.self) private var waits
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// A reminder was asked for with notifications refused (R-IB22): say where it waits.
    @State private var reminderDenied = false

    var body: some View {
        let ordered = FoundPolicy.order(inventory.items)
        let agents = ordered.filter { $0.group == .agents }
        let browsers = ordered.filter { $0.group == .browsers }
        let checking = inventory.isChecking && inventory.items.isEmpty
        // "Never blank", but never a false reason either (the `+` strip's rule):
        // the backend line only when the probe really had no answer.
        let backendDown = !inventory.isChecking && inventory.wiring == nil
        let nothingFound = agents.isEmpty && browsers.isEmpty && !inventory.isChecking && !backendDown

        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if !agents.isEmpty || checking || backendDown {
                section(Copy.welcomeYourAIApps) {
                    if checking { note(Copy.foundCheckingApps) } else if backendDown { note(Copy.foundBackendDown) }
                    ForEach(Array(agents.enumerated()), id: \.element.id) { index, item in row(item, index: index) }
                }
            }
            if !browsers.isEmpty {
                section(Copy.welcomeYourBrowsers) {
                    ForEach(Array(browsers.enumerated()), id: \.element.id) { index, item in
                        row(item, index: agents.count + index)
                    }
                }
            }
            if nothingFound { note(Copy.welcomeNothingFound) }
            section(Copy.welcomeYourChatHistory) { chatZone(roomy: agents.isEmpty && browsers.isEmpty) }
            section(Copy.welcomeWhoReads) { EngineChoice(pick: $pick) }
        }
    }

    // MARK: Sections

    /// Titled like Home's sections (caption caps, tertiary), so the Welcome and
    /// the page it becomes read as one family.
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(title)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: Found rows

    private func row(_ item: FoundItem, index: Int) -> some View {
        let agent = inventory.wiring?.agents.first { wiring in
            if case .agent(let id) = item.id { return wiring.id == id }
            return false
        }
        return FoundRow(mark: OnThisMacStrip.mark(item.id), title: item.title, detail: OnThisMacStrip.detail(item.id),
                        state: Self.rowState(item), disclosure: OnThisMacStrip.disclosure(agent),
                        action: action(for: item), tick: tickBinding(item))
            .opacity(revealed ? 1 : 0)
            .animation(CicadaMotion.reveal(index: index, reduceMotion: reduceMotion), value: revealed)
    }

    /// The machine's state before Start, as the `+` strip maps it — but an
    /// untouched row is `.off` here, never `.working`: nothing runs yet.
    static func rowState(_ item: FoundItem) -> FoundRowState {
        switch item.readiness {
        case .alreadyOn: .on
        case .needsPermission: .needsAction(Copy.foundAllow)
        case .failed(let why): .failed(why)
        default: .off
        }
    }

    /// Only two rows keep a button before Start: Allow… (a permission only the
    /// person can grant, in System Settings — W5: the row ticks itself when the
    /// grant lands) and Retry (a re-probe, which reads nothing).
    private func action(for item: FoundItem) -> (() -> Void)? {
        switch item.readiness {
        case .needsPermission:
            return {
                allowRequested.insert(item.id)
                touched.insert(item.id)
                NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)
            }
        case .failed:
            return { Task { await inventory.refresh() } }
        default:
            return nil
        }
    }

    /// nil for a row `WelcomeTicks.canTick` refuses (already on, still checking,
    /// blocked, failed) — a tick on a row Start cannot run would be a promise
    /// the start line then breaks. Any change marks the row touched, so a
    /// re-probe never overrides the person's answer (W4).
    private func tickBinding(_ item: FoundItem) -> Binding<Bool>? {
        guard WelcomeTicks.canTick(item) else { return nil }
        return Binding(
            get: { ticked.contains(item.id) },
            set: { on in
                touched.insert(item.id)
                if on { ticked.insert(item.id) } else { ticked.remove(item.id) }
            })
    }

    // MARK: Chat history (W10, W11)

    /// A dashed zone with the three vendors' real marks. The drop itself lands
    /// on the window's one target and the router stages it here (R-IB15), so
    /// this zone is a picture of where to drop, not a second drop target.
    private func chatZone(roomy: Bool) -> some View {
        let shape = RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            VStack(spacing: CicadaTheme.spacingSM) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    ForEach(ChatVendor.allCases) { VendorMark(vendor: $0, size: CicadaTheme.scaled(24)) }
                }
                Text(Copy.welcomeDropExport)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .multilineTextAlignment(.center)
                Button(Copy.intakeChooseFile) { Self.chooseFile(intake) }
                    .buttonStyle(.bordered)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, roomy ? CicadaTheme.spacingXL : CicadaTheme.spacingMD)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .background(dropTargeted ? CicadaTheme.meadowWash : Color.clear, in: shape)
            .overlay(shape.strokeBorder(dropTargeted ? CicadaTheme.meadow : CicadaTheme.border,
                                        style: StrokeStyle(lineWidth: dropTargeted ? 2 : 1, dash: [6, 4])))
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: dropTargeted)

            ForEach(intake.welcomeDrops) { drop in dropRow(drop) }
            if let error = intake.welcomeDropError {
                Text(error)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            askForOne
        }
    }

    // MARK: No export yet (W12, design §5.5)

    private var askLabel: some View {
        Text(Copy.welcomeAskForOne)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
    }

    @ViewBuilder private var askMenus: some View {
        ForEach(ChatVendor.allCases) { ExportAskMenu(vendor: $0) { reminderDenied = true } }
    }

    /// Three compact menus — the export page and *Remind me* per vendor — and, for
    /// each wait already asked for, its row line: the text twin that needs no
    /// notification permission. Nothing here is fetched or sent (R-IB22).
    private var askForOne: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            // One line when the card is wide enough, the label above the menus when
            // it is not (the Welcome's card narrows with the window and the zoom).
            ViewThatFits(in: .horizontal) {
                HStack(spacing: CicadaTheme.spacingSM) { askLabel; askMenus }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) { askLabel; HStack(spacing: CicadaTheme.spacingSM) { askMenus } }
            }
            ForEach(waits.active(bank: store.bank)) { wait in
                HStack(spacing: CicadaTheme.spacingXS) {
                    VendorMark(origin: ChatVendor(rawValue: wait.vendor)?.origin, size: CicadaTheme.scaled(14))
                    Text(ExportWaits.rowLine(wait, now: Date()))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            if reminderDenied {
                Text(Copy.reminderNotificationsOff)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// A staged export: ticked on arrival (the drop was the act, W11), untick to
    /// leave it out of Start, ✕ to un-stage it. Nothing is imported until Start.
    private func dropRow(_ drop: WelcomeDrop) -> some View {
        let title = IntakeSummary.previewTitle(drop.preview)
        return HStack(spacing: CicadaTheme.spacingXS) {
            FoundRow(mark: .logo(OriginIconography.logoName(for: drop.preview.origin ?? "") ?? ""),
                     title: title, detail: IntakeSummary.countsLine(drop.preview), state: .off,
                     tick: Binding(
                        get: { droppedTicked.contains(drop.id) },
                        set: { on in if on { droppedTicked.insert(drop.id) } else { droppedTicked.remove(drop.id) } }))
            Button {
                intake.removeWelcomeDrop(drop.id)
                droppedTicked.remove(drop.id)
            } label: {
                Image(systemName: "xmark")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .iconHover()
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.welcomeRemoveDrop)
            .accessibilityLabel("\(Copy.welcomeRemoveDrop), \(title)")
        }
    }

    /// What a staged drop contributes to Start's line — a saved-links file is
    /// counted as saved items, never as "conversations".
    static func foundItem(_ drop: WelcomeDrop) -> FoundItem {
        FoundItem(id: .dropped(drop.id), group: .chatHistory, title: IntakeSummary.previewTitle(drop.preview),
                  isPresent: true, content: .ownIntentionalAct, readiness: .ready, opensAnotherApp: false,
                  count: drop.preview.importCount,
                  countNoun: drop.preview.chatFiles.isEmpty ? "saved item"
                      : IntakeSummary.noun(vendor: drop.preview.vendor, count: 1))
    }

    /// The same panel `IntakePanel.chooseFile()` runs; the URLs go to the one
    /// intake, which stages them here because the Welcome is showing (R-IB15).
    static func chooseFile(_ intake: IntakeRouter) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.zip, .json, .html, .folder, .commaSeparatedText, .plainText, .xml, .propertyList]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = Copy.intakeDropTitle
        guard panel.runModal() == .OK else { return }
        intake.accept(urls: panel.urls, from: .welcome)
    }
}
