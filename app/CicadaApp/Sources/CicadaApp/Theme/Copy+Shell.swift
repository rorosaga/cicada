import Foundation

/// The shell's words (DS-1; DESIGN_RULES §5.1). Plain, sentence case, no jargon.
extension Copy {
    static let pages = "Pages"
    static let showIconRail = "Show icon rail"
    static let showLabelledSidebar = "Show labelled sidebar"
    static let switchToLight = "Switch to light appearance"
    static let switchToDark = "Switch to dark appearance"
    static let settingsHelp = "Settings (⌘,)"
    static let settingsAttentionHelp = "Settings — a connection needs you (⌘,)"
    static let settingsAttentionLabel = "Settings, a connection needs attention"
    /// Lower-case: it follows a comma or a middle dot ("Sleep · consolidating"). NOT
    /// `consolidating` — `Copy.swift:146` already declares that name ("Consolidating…"), and a
    /// second `static let consolidating` in an extension is a redeclaration error.
    static let railConsolidating = "consolidating"

    // The command bar (DR-23) and its one memory-bank selector (DR-24). "Project" is G141's word
    // now, so a bank is a "memory bank" everywhere the shell names it (R-DS19).
    static let searchYourMemory = "Search your memory"
    static let findInMemoryHelp = "Find in Memory… ⌘K"
    static let memoryBank = "Memory bank"
    static let memoryBanks = "Memory banks"
    static let switchMemoryBank = "Switch memory bank"
    static let noMemoryBanks = "No memory banks yet"
    static let newMemoryBankItem = "New memory bank…"
    static let saveMemoryBankAsItem = "Save as…"
    static let renameMemoryBankItem = "Rename…"
    static let newMemoryBankTitle = "New memory bank"
    static let newMemoryBankMessage = "Creates a new, empty memory bank."
    static let saveMemoryBankAsTitle = "Save memory bank as…"
    static let saveMemoryBankAsMessage = "Copies this memory bank under a new name."
    static let renameMemoryBankTitle = "Rename memory bank"
    static func renameMemoryBankMessage(_ name: String) -> String { "Renames \u{201C}\(name)\u{201D} in place." }
    static let renameMemoryBankFallback = "Renames the memory bank in place."
    static let memoryBankName = "Memory bank name"
    static let helpForThisPage = "Help for this page"

    // Settings as a panel inside the app (DR-33, R-DS21).
    static let settingsMenuItem = "Settings…"
    static let closeSettings = "Close settings"
    static let closeSettingsHelp = "Close (Esc)"
    static let pressEscToClose = "Press Esc to close"
}
