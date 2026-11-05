import AppKit
import SwiftUI

// G161 (ROR-111; owner: "a button to go to that note … it takes you to the website with that repo") — one control on a
// source's item that opens it where it lives. The backend says which rows have a place and answers it for one item on
// the click (`GET /sources/channels/{id}/items/{item}/place`); the app only opens it. DR-40, DR-53, DR-69: `IconButton`.

/// The kinds a row may say. An unknown word from a newer backend is no control.
enum ItemPlaceKind: String, Sendable {
    case notes, github, web

    var help: String {
        switch self {
        case .notes: Copy.Place.inNotes
        case .github: Copy.GitHub.openOnGitHub
        case .web: Copy.Place.inBrowser
        }
    }
}

/// `GET …/place`: `{kind: "notes", note_id}` or `{kind: "github"|"web", url}`.
struct ItemPlace: Codable, Equatable, Sendable {
    var kind: String
    var url: String? = nil
    var noteId: String? = nil

    enum CodingKeys: String, CodingKey {
        case kind, url
        case noteId = "note_id"
    }
}

/// The decisions, with no view in them. A stored URL is data, whoever sent it: this is checked again at the last step.
enum ItemPlaceOpen {
    enum Target: Equatable {
        case web(URL)
        case note(String)
    }

    struct Deps: Sendable {
        var openURL: @MainActor @Sendable (URL) -> Void
        var showNote: AppleNotesReader.ShowRunner

        static let live = Deps(openURL: { NSWorkspace.shared.open($0) }, showNote: AppleNotesReader.runShow)
    }

    /// Only a plain http(s) link with a host opens: never `file:`, a custom scheme, or a link carrying credentials.
    static func webURL(_ raw: String) -> URL? {
        guard !raw.unicodeScalars.contains(where: { $0.value <= 32 || $0 == "\\" }),
              let url = URL(string: raw), let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = url.host, !host.isEmpty, url.user == nil, url.password == nil else { return nil }
        return url
    }

    /// Notes' own id for a note and nothing else: it travels as an argument, and this keeps a stored oddity out too.
    static func noteID(_ raw: String) -> String? {
        let prefix = "x-coredata://"
        guard raw.hasPrefix(prefix), raw.count > prefix.count else { return nil }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "._/-:"))
        return raw.unicodeScalars.allSatisfy { $0.isASCII && allowed.contains($0) } ? raw : nil
    }

    static func target(_ place: ItemPlace) -> Target? {
        switch ItemPlaceKind(rawValue: place.kind) {
        case .notes:
            return place.noteId.flatMap(noteID).map(Target.note)
        case .github:
            guard let url = place.url.flatMap(webURL), ["github.com", "www.github.com"].contains(url.host?.lowercased())
            else { return nil }
            return .web(url)
        case .web:
            return place.url.flatMap(webURL).map(Target.web)
        case nil:
            return nil
        }
    }

    /// Runs only on the person's click. Returns the words to show when it could not open, nil when it did.
    @MainActor
    static func open(resolve: () async throws -> ItemPlace, deps: Deps = .live) async -> String? {
        guard let place = try? await resolve(), let target = target(place) else { return Copy.Place.notFound }
        switch target {
        case .web(let url):
            deps.openURL(url)
            return nil
        case .note(let id):
            return AppleNotesReader.showProblem(await deps.showNote(id, AppleNotesReader.showTimeout))
        }
    }
}

/// Adds the control to a row: on its trailing edge, over the row rather than inside its button, so a click on it never
/// also opens the row. A row calls `reserve` to keep its own text clear of it. A failure is one line under the row until
/// the next press. No `kind`, no control.
struct ItemPlaceControl: ViewModifier {
    let kind: ItemPlaceKind?
    let title: String
    let resolve: () async throws -> ItemPlace

    @State private var problem: String?
    @State private var opening = false

    static func reserve(_ kind: ItemPlaceKind?) -> CGFloat {
        kind == nil ? 0 : CicadaTheme.scaled(28) + CicadaTheme.spacingSM
    }

    func body(content: Content) -> some View {
        if let kind {
            VStack(alignment: .leading, spacing: 0) {
                content.overlay(alignment: .trailing) {
                    IconButton(systemName: "arrow.up.forward.square", help: kind.help,
                               accessibilityLabel: "\(kind.help), \(title)", action: press)
                        .padding(.trailing, CicadaTheme.spacingXS)
                }
                if let problem {
                    Text(problem)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(2)
                        .padding(.horizontal, CicadaTheme.scaled(10))
                        .help(problem)
                }
            }
        } else {
            content
        }
    }

    private func press() {
        guard !opening else { return }
        opening = true
        problem = nil
        Task {
            problem = await ItemPlaceOpen.open(resolve: resolve)
            opening = false
        }
    }
}

extension ChannelItem {
    var placeKind: ItemPlaceKind? { place.flatMap(ItemPlaceKind.init(rawValue:)) }
}
