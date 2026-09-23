import Foundation

/// The palette's actions table (design §3.3, trimmed by R-SU13). Each title is
/// the verb the page that owns the action already uses, and each runs the same
/// call that page makes (`ContentView.openFind`).
enum PaletteActions {
    static func docs(_ inputs: QuickIndexInputs) -> [QuickIndex.Doc] {
        var docs: [QuickIndex.Doc] = []
        func add(_ id: String, _ title: String, keywords: [String], symbol: String, trailing: String? = nil,
                 destination: FindDestination, kind: FindKind = .action, order: Int) {
            let row = FindRow(key: FindRowKey(kind: kind, id: id), group: .actions, title: title,
                              mark: .symbol(symbol), trailing: trailing, tieBreak: -Double(order),
                              destination: destination)
            docs.append(QuickIndex.Doc(row: row, fields: [QuickMatch.Field(title, weight: QuickMatch.Weight.name)]
                + keywords.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }))
        }
        if inputs.isSleeping {
            add("stop-consolidating", "Stop consolidating", keywords: ["sleep", "cancel", "stop"],
                symbol: "stop.circle", destination: .action(.stopConsolidating), order: 0)
        } else if inputs.unprocessed > 0 {
            // The Sleep page's own gate (`SleepPageModel.consolidateEnabled`,
            // R-A7): nothing queued, nothing to run.
            add("consolidate", "Consolidate now", keywords: ["sleep", "run", "consolidate"],
                symbol: "moon.zzz", destination: .action(.consolidate), order: 0)
        }
        for (i, tab) in AppTab.allCases.enumerated() {
            add("tab.\(tab.rawValue)", "Go to \(tab.title)", keywords: ["open", "page", "show"], symbol: tab.icon,
                trailing: i < 9 ? "⌘\(i + 1)" : nil, destination: .tab(tab), order: 10 + i)
        }
        if inputs.appearance == .dark {
            add("appearance.light", "Switch to light", keywords: ["appearance", "theme", "day"],
                symbol: "sun.max", destination: .action(.lightMode), order: 30)
        } else {
            add("appearance.dark", "Switch to dark", keywords: ["appearance", "theme", "night"],
                symbol: "moon", destination: .action(.darkMode), order: 30)
        }
        add("zoom.in", "Zoom in", keywords: ["text size", "bigger", "larger"], symbol: "plus.magnifyingglass",
            trailing: "⌘+", destination: .action(.zoomIn), order: 31)
        add("zoom.out", "Zoom out", keywords: ["text size", "smaller"], symbol: "minus.magnifyingglass",
            trailing: "⌘−", destination: .action(.zoomOut), order: 32)
        add("zoom.reset", "Actual size", keywords: ["text size", "zoom", "reset"], symbol: "1.magnifyingglass",
            trailing: "⌘0", destination: .action(.actualSize), order: 33)
        for (i, bank) in inputs.banks.enumerated() where bank.name != inputs.activeBank {
            add(bank.name, "Switch to \(bank.name)", keywords: ["memory bank", "bank", "switch"], symbol: "tray.2",
                destination: .bank(name: bank.name), kind: .bank, order: 40 + i)
        }
        return docs
    }

    /// The empty state's suggestions (design §3.6), each only when it is true.
    static func suggested(_ inputs: QuickIndexInputs) -> [FindRow] {
        var rows: [FindRow] = []
        if !inputs.isSleeping && inputs.unprocessed > 0 {
            rows.append(FindRow(key: FindRowKey(kind: .action, id: "suggest.consolidate"), group: .suggested,
                                title: "Consolidate now", detail: "New memories are waiting to be read",
                                mark: .symbol("moon.zzz"), destination: .action(.consolidate)))
        }
        if !inputs.inbox.isEmpty {
            let n = inputs.inbox.count
            rows.append(FindRow(key: FindRowKey(kind: .action, id: "suggest.inbox"), group: .suggested,
                                title: n == 1 ? "Answer 1 question" : "Answer \(UsageFormat.count(n)) questions",
                                mark: .symbol("tray.full"), destination: .tab(.inbox)))
        }
        return rows
    }
}
