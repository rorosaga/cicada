import Foundation

/// A skin over the same state/tag/canvas contract. Paths are repository-relative provenance, never viewer data.
struct Mascot: Identifiable, Equatable, Sendable {
    let id: String
    let displayName: String
    let roomSheetPrefix: String
    let menuBarSheet: String
    let artFolder: String

    func roomSheet(_ state: BookwormState, lighting: RoomLighting = .day, lampLit: Bool = false) -> String {
        "\(roomSheetPrefix)\(state.caseName)\(lighting.suffix(lampLit: lampLit))"
    }

    func selectionLabel(selected: Bool) -> String {
        selected ? "\(displayName), selected" : displayName
    }
}

/// The complete, ordered catalog. Adding a skin adds its sheets/manifest entries and one catalog entry.
enum MascotRegistry {
    static let bookworm = Mascot(id: "bookworm", displayName: "Bookworm", roomSheetPrefix: "bookworm-",
                                menuBarSheet: "bookworm-small", artFolder: "app/CicadaApp/Art/sprites/bookworm-2026-10-01")
    static let all = [bookworm]

    static func resolve(_ storedID: String) -> Mascot {
        all.first { $0.id == storedID } ?? bookworm
    }
}

/// Per-viewer preferences, separate from every bank. Views observe this key with AppStorage.
enum MascotPreference {
    static let defaultsKey = "cicada.mascot"
    static func selected(in defaults: UserDefaults = .standard) -> Mascot {
        MascotRegistry.resolve(defaults.string(forKey: defaultsKey) ?? MascotRegistry.bookworm.id)
    }
}
