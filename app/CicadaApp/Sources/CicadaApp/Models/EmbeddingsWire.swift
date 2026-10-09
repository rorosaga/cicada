import Foundation

// G182 phase 3 — Settings → Memory → Search model. The wire of `GET /embeddings` (and the
// same shape back from `POST /embeddings/choice` and `/embeddings/install`), plus the pure
// pieces the row says out loud. Every field optional-with-default so an older or newer
// backend decodes. Not a Store domain and no ETag: the page reads it when it opens and
// polls while a download or the background re-embed runs (EmbeddingGemma 2, 2026-10-09).

/// One model the backend offers (`api/services/embedding_models.py::CATALOG`).
struct EmbeddingModelOption: Codable, Equatable, Hashable, Identifiable {
    var id: String
    var label: String
    var dimensions: Int = 0
    var detail: String = ""
    var needsDownload: Bool = false
    /// The download needs the person's own account token (the larger model); the Neural Engine model's doesn't.
    var needsToken: Bool = false
    var available: Bool = true

    init(id: String, label: String, dimensions: Int = 0, detail: String = "",
         needsDownload: Bool = false, needsToken: Bool? = nil, available: Bool = true) {
        self.id = id; self.label = label; self.dimensions = dimensions; self.detail = detail
        self.needsDownload = needsDownload; self.needsToken = needsToken ?? needsDownload; self.available = available
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = (try? c.decode(String.self, forKey: .label)) ?? id
        dimensions = (try? c.decode(Int.self, forKey: .dimensions)) ?? 0
        detail = (try? c.decode(String.self, forKey: .detail)) ?? ""
        needsDownload = (try? c.decode(Bool.self, forKey: .needsDownload)) ?? false
        // An older backend's one download was the larger model's, which always needed the token.
        needsToken = (try? c.decode(Bool.self, forKey: .needsToken)) ?? needsDownload
        available = (try? c.decode(Bool.self, forKey: .available)) ?? true
    }
}

/// The larger model's one-time install: `idle|installing|done|failed`, what it is doing now
/// and why it stopped — both already in words, written by the backend for the person.
struct EmbeddingInstallState: Codable, Equatable {
    var state: String = "idle"
    var step: String = ""
    var error: String = ""

    init(state: String = "idle", step: String = "", error: String = "") {
        self.state = state; self.step = step; self.error = error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = (try? c.decode(String.self, forKey: .state)) ?? "idle"
        step = (try? c.decode(String.self, forKey: .step)) ?? ""
        error = (try? c.decode(String.self, forKey: .error)) ?? ""
    }

    var isInstalling: Bool { state == "installing" }
}

/// The background re-embed after a model change: `idle|running|waiting|done|failed`, how many of the
/// bank's tables already hold the new model, and why it stopped (a sentence from the backend).
struct EmbeddingReindexState: Codable, Equatable {
    var state: String = "idle"
    var model: String = ""
    var done: Int = 0
    var total: Int = 0
    var error: String = ""

    init(state: String = "idle", model: String = "", done: Int = 0, total: Int = 0, error: String = "") {
        self.state = state; self.model = model; self.done = done; self.total = total; self.error = error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = (try? c.decode(String.self, forKey: .state)) ?? "idle"
        model = (try? c.decode(String.self, forKey: .model)) ?? ""
        done = (try? c.decode(Int.self, forKey: .done)) ?? 0
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
        error = (try? c.decode(String.self, forKey: .error)) ?? ""
    }

    /// Running, or waiting for Sleep to finish: the page keeps polling.
    var isActive: Bool { state == "running" || state == "waiting" }
}

/// `GET /embeddings`. `model` is what the active bank's vectors use now; `nextModel` is what the
/// bank is built with — the two differ right after a change, until the background re-embed (or,
/// for a hosted model, the next Sleep) has moved every table. `recommended` names the model this
/// Mac runs best when it isn't downloaded yet.
struct EmbeddingsStatus: Codable, Equatable {
    var model: String
    var nextModel: String
    var choice: String? = nil
    var release: Bool = false
    var recommended: String? = nil
    var models: [EmbeddingModelOption] = []
    var install = EmbeddingInstallState()
    var reindex = EmbeddingReindexState()

    init(model: String, nextModel: String? = nil, choice: String? = nil, release: Bool = false,
         recommended: String? = nil, models: [EmbeddingModelOption] = [],
         install: EmbeddingInstallState = EmbeddingInstallState(), reindex: EmbeddingReindexState = EmbeddingReindexState()) {
        self.model = model; self.nextModel = nextModel ?? model; self.choice = choice
        self.release = release; self.recommended = recommended; self.models = models; self.install = install
        self.reindex = reindex
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        model = (try? c.decode(String.self, forKey: .model)) ?? ""
        nextModel = (try? c.decode(String.self, forKey: .nextModel)) ?? model
        choice = try? c.decodeIfPresent(String.self, forKey: .choice)
        release = (try? c.decode(Bool.self, forKey: .release)) ?? false
        recommended = try? c.decodeIfPresent(String.self, forKey: .recommended)
        models = (try? c.decode([EmbeddingModelOption].self, forKey: .models)) ?? []
        install = (try? c.decode(EmbeddingInstallState.self, forKey: .install)) ?? EmbeddingInstallState()
        reindex = (try? c.decode(EmbeddingReindexState.self, forKey: .reindex)) ?? EmbeddingReindexState()
    }

    func option(_ id: String) -> EmbeddingModelOption? { models.first { $0.id == id } }

    /// The model a download is about: one not on this Mac yet (the recommended one first), else any that needs one.
    var downloadable: EmbeddingModelOption? {
        if let id = recommended, let rec = option(id), !rec.available { return rec }
        return models.first { $0.needsDownload && !$0.available } ?? models.first { $0.needsDownload }
    }

    /// Something is moving: a download, or the re-embed after a change. The page polls while it is.
    var isBusy: Bool { install.isInstalling || reindex.isActive }
}

/// What a pick in the Search model picker does — pure, so the routing is tested without a view.
enum SearchModelRoute: Equatable {
    /// Already the model the next sync builds with, or an install is running: nothing to send.
    case nothing
    /// Sleep is writing; the picker is disabled and says why (DR-41), this is the belt to that brace.
    case blocked
    /// Not on this Mac yet and its download needs the person's token — the pick opens the install sheet.
    case install
    /// Not on this Mac yet, no account needed — the pick starts the one-time download (`POST /embeddings/install`).
    case download(String)
    /// `POST /embeddings/choice` with this id.
    case choose(String)
}

enum SearchModelLogic {
    /// How often the row re-reads `GET /embeddings` while an install runs.
    static let pollInterval: Duration = .seconds(2)

    static func route(picked id: String, status: EmbeddingsStatus, sleepWriting: Bool) -> SearchModelRoute {
        guard id != status.nextModel else { return .nothing }
        if sleepWriting { return .blocked }
        guard let option = status.option(id) else { return .nothing }
        if !option.available {
            if status.install.isInstalling { return .nothing }
            return option.needsToken ? .install : .download(id)
        }
        return .choose(id)
    }

    /// The Install button waits for something shaped like a token (the backend checks the rest).
    static func tokenLooksValid(_ token: String) -> Bool {
        token.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("hf_")
    }

    /// The model's own page, where the person accepts its license with their own account.
    static func modelPage(_ id: String) -> URL? { URL(string: "https://huggingface.co/\(id)") }
    static let tokensPage = URL(string: "https://huggingface.co/settings/tokens")!

    /// The row's detail line, in words, for every state (DR-37: it shares the card with Search index).
    /// An install in progress outranks everything; a failure outranks a pending switch only while the
    /// model it was for is still missing; a pending switch outranks what the bank uses now.
    static func detail(_ status: EmbeddingsStatus?) -> String? {
        guard let status else { return nil }
        let install = status.install
        if install.isInstalling {
            return install.step.isEmpty ? Copy.SearchModel.installingGeneric : Copy.SearchModel.installing(install.step)
        }
        if install.state == "failed", !install.error.isEmpty, status.downloadable?.available != true {
            return install.error
        }
        let reindex = status.reindex
        if reindex.state == "running" {
            return Copy.SearchModel.moving(label(reindex.model, in: status), done: reindex.done, total: reindex.total)
        }
        if reindex.state == "waiting" { return Copy.SearchModel.movingAfterSleep(label(reindex.model, in: status)) }
        if reindex.state == "failed", !reindex.error.isEmpty, status.nextModel != status.model { return reindex.error }
        if !status.nextModel.isEmpty, status.nextModel != status.model {
            return Copy.SearchModel.switchesAtNextSleep(label(status.nextModel, in: status))
        }
        if install.state == "done", let ready = status.downloadable, ready.available, ready.id != status.nextModel {
            return Copy.SearchModel.installedChoose(ready.label)
        }
        guard let current = status.option(status.model) else { return Copy.SearchModel.usesOther }
        // A bank built with the larger model on a Mac without it keeps its vectors (never re-embedded behind the
        // person's back); until the install, search reads words.
        if current.needsDownload, !current.available { return Copy.SearchModel.builtWithMissing(current.label) }
        if let id = status.recommended, id != current.id, let better = status.option(id), !better.available {
            return Copy.SearchModel.usesNowBetterHere(current.label, better: better.label)
        }
        return Copy.SearchModel.usesNow(current.label, detail: current.detail)
    }

    static func label(_ id: String, in status: EmbeddingsStatus) -> String {
        status.option(id)?.label ?? Copy.SearchModel.anotherModel
    }
}
