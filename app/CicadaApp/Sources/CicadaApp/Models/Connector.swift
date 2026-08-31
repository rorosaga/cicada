import Foundation

/// One credential a saved-content connector needs. `present` says whether it is
/// stored; the VALUE never crosses the wire in this direction — the backend has
/// no endpoint that returns it.
struct ConnectorField: Codable, Hashable, Identifiable {
    let name: String
    let label: String
    let secret: Bool
    let present: Bool

    var id: String { name }
}

/// A direct-API saved-content connector (G71 §2). Deliberately NOT a
/// `ConnectionStatus`: that type describes an LLM engine and feeds engine
/// selection, and a Pinterest account is not an engine.
struct ConnectorStatus: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let connected: Bool
    let fields: [ConnectorField]
    let lastSync: String?
    let lastError: String?
    let detail: String?
    /// "oauth" (save app keys, then authorize in a browser) or "credentials".
    let loginMode: String

    var isOAuth: Bool { loginMode == "oauth" }

    /// Keys are saved but no token has been granted yet — the state where the
    /// panel must show "Authorize in your browser", not "Save".
    var needsAuthorization: Bool {
        isOAuth && !connected && !fields.isEmpty && fields.allSatisfy(\.present)
    }
}

struct ConnectorsResponse: Codable {
    let connectors: [ConnectorStatus]
}

struct ConnectorAuthorizeResponse: Codable {
    let authorizeUrl: String
    let state: String
}

struct ConnectorSyncResult: Codable {
    let status: String
    let reason: String?
    let new: Int
    let seen: Int
    let error: String?
}
