import Foundation

/// Cicada's own skills (G138), by their installed folder name. the Skills page listed them until D6; the Skills page
/// and the tests still name them.
enum CicadaSkillBundle: String, CaseIterable, Identifiable {
    case cicada
    case cicadaLibrarian = "cicada-librarian"
    /// 2026-10-16: when the person asks about someone, their agent reads that one LinkedIn profile in their browser.
    case linkedinPeople = "linkedin-people"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .cicada: "Recall and save"
        case .cicadaLibrarian: "Tidy as you work"
        case .linkedinPeople: "What people do now"
        }
    }
    var summary: String {
        switch self {
        case .cicada: "Tells your agent when to look things up in Cicada and when to save."
        case .cicadaLibrarian: "Lets your agent file what you just did into Cicada, the way Sleep would."
        case .linkedinPeople:
            "When you ask about someone, your agent reads their LinkedIn profile in your browser and updates what Cicada knows."
        }
    }
}
