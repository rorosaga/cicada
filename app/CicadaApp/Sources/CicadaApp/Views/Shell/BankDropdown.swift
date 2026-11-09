import SwiftUI

/// The memory switcher's dropdown (app-fixes-1109, owner 2026-11-09: "an actual app component that smoothly drops
/// down… a little stat icon fill showing how big they are… drag them to change the order… an add a new one option in
/// the bottom… after a certain number it converts into a scrollable list").
///
/// A popover under the command bar's name, not a system menu. One row per memory: a check on the current one, its name,
/// and a small gauge — its size (entities and conversations together) against the largest memory, the counts on hover
/// and spoken. Drag a row onto another to reorder, or ⌥↑ / ⌥↓ on the highlighted one; the server keeps the order
/// (`POST /banks/order`). The list scrolls past `BankOrder.visibleRows`. *New memory…* is pinned under it, *Save as…* and
/// *Rename…* beside it. Keys: ↑ ↓ move the highlight, Return switches, Esc closes. DR-9 (a ring, no shadow of ours),
/// DR-12 (concentric corners), DR-40 (neutral controls), DR-60 (a keyboard action never animates; a drop settles on
/// `CicadaMotion.settle`), DR-63 (everything scales with the text size).
struct BankDropdown: View {
    let banksVM: BanksViewModel
    let host: String?
    let choose: (String) -> Void
    let create: () -> Void
    let saveAs: () -> Void
    let rename: () -> Void

    @State private var highlighted: String?
    @State private var dropTarget: String?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var focused: Bool

    static let rowHeight: CGFloat = 32
    static let width: CGFloat = 300

    var body: some View {
        let banks = banksVM.banks
        VStack(alignment: .leading, spacing: 0) {
            if let host {
                Text(host)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.top, CicadaTheme.spacingSM)
            }
            if banks.isEmpty {
                Text(Copy.noMemoryBanks)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(CicadaTheme.spacingMD)
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.scaled(2)) {
                        ForEach(banks) { bank in
                            row(bank, among: banks)
                        }
                    }
                    .padding(CicadaTheme.scaled(6))
                }
                .frame(height: listHeight(count: banks.count))
            }
            Rectangle().fill(CicadaTheme.ring(.edge)).frame(height: 1)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                action(Copy.newMemoryItem, systemImage: "plus", enabled: true, run: create)
                action(Copy.saveMemoryBankAsItem, systemImage: "square.on.square", enabled: banksVM.activeName != nil, run: saveAs)
                action(Copy.renameMemoryBankItem, systemImage: "pencil", enabled: banksVM.activeName != nil, run: rename)
            }
            .padding(CicadaTheme.scaled(6))
        }
        .frame(width: CicadaTheme.scaled(Self.width))
        .background(CicadaTheme.surface)
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onAppear { highlighted = banksVM.activeName; focused = true }
        .onKeyPress(.upArrow, phases: [.down, .repeat]) { press in key(-1, press, banks) }
        .onKeyPress(.downArrow, phases: [.down, .repeat]) { press in key(1, press, banks) }
        .onKeyPress(.return) {
            guard let highlighted else { return .ignored }
            choose(highlighted)
            return .handled
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.memoryBanks)
    }

    private func listHeight(count: Int) -> CGFloat {
        let rows = CGFloat(min(count, BankOrder.visibleRows))
        return CicadaTheme.scaled(Self.rowHeight) * rows + CicadaTheme.scaled(2) * max(0, rows - 1) + CicadaTheme.scaled(12)
    }

    private func row(_ bank: MemoryBank, among banks: [MemoryBank]) -> some View {
        let isCurrent = bank.name == banksVM.activeName
        return BankDropdownRow(bank: bank, isCurrent: isCurrent, isHighlighted: highlighted == bank.name,
                               fill: BankOrder.fill(bank, among: banks), isDropTarget: dropTarget == bank.name,
                               hover: { inside in if inside { highlighted = bank.name } },
                               choose: { choose(bank.name) })
            .draggable(bank.name)
            .dropDestination(for: String.self) { items, _ in
                guard let dragged = items.first else { return false }
                // A pointer's drop settles; a key never animates (DR-60).
                let move = { Task { await banksVM.reorder(BankOrder.moved(banks.map(\.name), dragged, before: bank.name)) } }
                if let animation = AppearanceMotion.current() { withAnimation(animation) { move() } } else { move() }
                return true
            } isTargeted: { dropTarget = $0 ? bank.name : (dropTarget == bank.name ? nil : dropTarget) }
    }

    private func key(_ step: Int, _ press: KeyPress, _ banks: [MemoryBank]) -> KeyPress.Result {
        let names = banks.map(\.name)
        guard !names.isEmpty else { return .ignored }
        let at = highlighted.flatMap(names.firstIndex(of:)) ?? names.firstIndex(of: banksVM.activeName ?? "") ?? 0
        if press.modifiers.contains(.option), let highlighted {
            // A reorder from the keyboard: one frame, the highlight stays on the memory that moved.
            Task { await banksVM.reorder(BankOrder.nudged(names, highlighted, by: step)) }
            return .handled
        }
        highlighted = names[min(max(at + step, 0), names.count - 1)]
        return .handled
    }

    private func action(_ title: String, systemImage: String, enabled: Bool, run: @escaping () -> Void) -> some View {
        BankDropdownAction(title: title, systemImage: systemImage, enabled: enabled, run: run)
    }
}

private struct BankDropdownRow: View {
    let bank: MemoryBank
    let isCurrent: Bool
    let isHighlighted: Bool
    let fill: Double
    let isDropTarget: Bool
    let hover: (Bool) -> Void
    let choose: () -> Void

    var body: some View {
        Button(action: choose) {
            HStack(spacing: CicadaTheme.scaled(8)) {
                Image(systemName: "checkmark")
                    .font(CicadaTheme.font(size: 11, weight: .semibold))
                    .frame(width: CicadaTheme.scaled(14))
                    .opacity(isCurrent ? 1 : 0)
                    .accessibilityHidden(true)
                Text(bank.name)
                    .font(CicadaTheme.rowFont)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: CicadaTheme.scaled(8))
                gauge
            }
            .foregroundStyle(isCurrent || isHighlighted ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(height: CicadaTheme.scaled(BankDropdown.rowHeight))
            .rowHoverFill(hovering: isHighlighted)
            .overlay(alignment: .top) {
                // Where a dragged memory will land: a strong ring line above this row.
                if isDropTarget { Rectangle().fill(CicadaTheme.ring(.strong)).frame(height: 2) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover(perform: hover)
        .help(BankSwitcher.label(name: bank.name, entities: bank.entityCount, episodes: bank.episodeCount))
        .accessibilityLabel(bank.name)
        .accessibilityValue(BankSwitcher.label(name: "", entities: bank.entityCount, episodes: bank.episodeCount)
            .trimmingCharacters(in: CharacterSet(charactersIn: " ()")))
        .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
    }

    /// The size, against the largest memory: a ringed track and a fill (DR-9: a ring, not a border of our own colour).
    private var gauge: some View {
        let width = CicadaTheme.scaled(44)
        return ZStack(alignment: .leading) {
            Capsule().fill(CicadaTheme.bgSelected)
            Capsule().fill(isCurrent ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                .frame(width: width * fill)
        }
        .frame(width: width, height: CicadaTheme.scaled(5))
        .accessibilityHidden(true)
    }
}

private struct BankDropdownAction: View {
    let title: String
    let systemImage: String
    let enabled: Bool
    let run: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: run) {
            HStack(spacing: CicadaTheme.scaled(8)) {
                Image(systemName: systemImage)
                    .font(CicadaTheme.font(size: 12, weight: .medium))
                    .frame(width: CicadaTheme.scaled(14))
                Text(title).font(CicadaTheme.rowFont)
                Spacer(minLength: 0)
            }
            .foregroundStyle(hovering && enabled ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(height: CicadaTheme.scaled(BankDropdown.rowHeight))
            .rowHoverFill(hovering: hovering && enabled)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : NeutralButton.disabledOpacity)
        .onHover { hovering = $0 }
    }
}
