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
}
