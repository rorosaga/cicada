import Foundation

// G182 phase 3 — Settings → Search & files (was Memory → Search model). The wire of `GET /embeddings` (and the
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
    /// What its one-click download fetches, from Cicada's own pins — stated before the click; 0 when not known.
    var downloadBytes: Int = 0

    init(id: String, label: String, dimensions: Int = 0, detail: String = "",
         needsDownload: Bool = false, needsToken: Bool? = nil, available: Bool = true, downloadBytes: Int = 0) {
        self.id = id; self.label = label; self.dimensions = dimensions; self.detail = detail
        self.needsDownload = needsDownload; self.needsToken = needsToken ?? needsDownload; self.available = available
        self.downloadBytes = downloadBytes
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
        downloadBytes = (try? c.decode(Int.self, forKey: .downloadBytes)) ?? 0
    }
}

/// The larger model's one-time install: `idle|installing|done|failed`, what it is doing now
/// and why it stopped — both already in words, written by the backend for the person.
///
/// Search & files — `part` says which download the one job runs (`text`, `vision` or `larger`), so a step lands on the
/// right row; empty from an older backend, which is read as the meaning download. `done`/`total` are bytes while a
/// pinned download streams (0 otherwise), so the row draws a real bar instead of a guess.
struct EmbeddingInstallState: Codable, Equatable {
    var state: String = "idle"
    var step: String = ""
    var error: String = ""
    var part: String = ""
    var done: Int = 0
    var total: Int = 0

    static let partText = "text"
    static let partVision = "vision"
    static let partLarger = "larger"

    init(state: String = "idle", step: String = "", error: String = "", part: String = "", done: Int = 0, total: Int = 0) {
        self.state = state; self.step = step; self.error = error; self.part = part; self.done = done; self.total = total
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = (try? c.decode(String.self, forKey: .state)) ?? "idle"
        step = (try? c.decode(String.self, forKey: .step)) ?? ""
        error = (try? c.decode(String.self, forKey: .error)) ?? ""
        part = (try? c.decode(String.self, forKey: .part)) ?? ""
        done = (try? c.decode(Int.self, forKey: .done)) ?? 0
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
    }

    var isInstalling: Bool { state == "installing" }
    /// The image part's download (Understand images); anything else is the meaning row's.
    var isVision: Bool { part == Self.partVision }
}

/// Search & files — whether this Mac can understand images (`GET /embeddings`'s `vision`, which the backend served
/// before the app read it): `supported` (macOS 15+ on Apple silicon), `installed`, the one-time download's size and
/// whether that size `includesText` (the text part is fetched first when it isn't here — the Looks shortcut).
struct EmbeddingVisionState: Codable, Equatable {
    var supported: Bool = false
    var installed: Bool = false
    var downloadBytes: Int = 0
    var includesText: Bool = false

    init(supported: Bool = false, installed: Bool = false, downloadBytes: Int = 0, includesText: Bool = false) {
        self.supported = supported; self.installed = installed; self.downloadBytes = downloadBytes
        self.includesText = includesText
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        supported = (try? c.decode(Bool.self, forKey: .supported)) ?? false
        installed = (try? c.decode(Bool.self, forKey: .installed)) ?? false
        downloadBytes = (try? c.decode(Int.self, forKey: .downloadBytes)) ?? 0
        includesText = (try? c.decode(Bool.self, forKey: .includesText)) ?? false
    }
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
    /// nil from a backend that doesn't say — then the page shows no images row rather than a guessed one.
    var vision: EmbeddingVisionState? = nil

    init(model: String, nextModel: String? = nil, choice: String? = nil, release: Bool = false,
         recommended: String? = nil, models: [EmbeddingModelOption] = [],
         install: EmbeddingInstallState = EmbeddingInstallState(), reindex: EmbeddingReindexState = EmbeddingReindexState(),
         vision: EmbeddingVisionState? = nil) {
        self.model = model; self.nextModel = nextModel ?? model; self.choice = choice
        self.release = release; self.recommended = recommended; self.models = models; self.install = install
        self.reindex = reindex; self.vision = vision
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
        vision = try? c.decodeIfPresent(EmbeddingVisionState.self, forKey: .vision)
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
    /// Not on this Mac yet, no account needed. The pick sends NOTHING: a selection is never the consent. It asks for a
    /// confirm that names the size (`SearchModelLogic.confirmation`), and only that explicit *Download* button sends
    /// `POST /embeddings/install` (review B1, 2026-10-14).
    case confirmDownload(String)
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
            return option.needsToken ? .install : .confirmDownload(id)
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

    /// Advanced → Search version's detail line, in words, for every state (DR-37: it shares the card with Rebuild
    /// search). An install in progress outranks everything; a failure outranks a pending switch only while the
    /// version it was for is still missing; a pending switch outranks what the bank uses now. The image part's
    /// download belongs to *Understand images*, never to this line.
    static func detail(_ status: EmbeddingsStatus?) -> String? {
        guard let status else { return nil }
        let install = status.install
        if install.isInstalling, !install.isVision {
            return install.step.isEmpty ? Copy.SearchModel.installingGeneric : Copy.SearchModel.installing(install.step)
        }
        if install.state == "failed", !install.error.isEmpty, !install.isVision, status.downloadable?.available != true {
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

    /// The confirm a not-installed pick raises, naming what it fetches before the explicit *Download* click.
    static func confirmation(for id: String, in status: EmbeddingsStatus) -> String {
        let option = status.option(id)
        return Copy.SearchModel.confirmDownload(option?.label ?? Copy.SearchModel.anotherModel, bytes: option?.downloadBytes ?? 0)
    }

    static func label(_ id: String, in status: EmbeddingsStatus) -> String {
        status.option(id)?.label ?? Copy.SearchModel.anotherModel
    }
}

// MARK: - Search & files: the two consent rows (owner, 2026-10-14)

/// What a row's one button does. Each is the person's click, never the page's own move (network rail).
enum UnderstandAction: Equatable {
    /// `POST /embeddings/install` with this id — the sharper version's one-time download, which ends by switching
    /// search to it (the backend's re-read starts when the download lands). A choice that would keep it off is
    /// cleared first, so one click means "use it" (REVIEW §2.2).
    case fetchMeaning(String)
    /// `POST /embeddings/choice` with this id — the sharper version is already on this Mac; use it.
    case chooseMeaning(String)
    /// `POST /embeddings/install` with `part: vision` — the image part, its own second click.
    case fetchImages
}

/// One consent row's state, in words — pure, so every state is tested without a view.
struct UnderstandRow: Equatable {
    var detail: String
    /// The detail is a failure's sentence: drawn after one `warning` glyph, the text itself untinted (DR-7).
    var failed = false
    /// A download or a re-read is moving: a bar when `total` (bytes) is known, else a small spinner.
    var busy = false
    var done = 0
    var total = 0
    /// Shows "On" where a button would be.
    var on = false
    var button: String? = nil
    var action: UnderstandAction? = nil
    var enabled = true
    /// The button's `.help`: what the click does, or — disabled — why it waits (DR-41).
    var help: String? = nil
}

enum SearchUnderstanding {
    /// The catalog's one-click download (no account): the sharper version.
    static func sharper(_ status: EmbeddingsStatus) -> EmbeddingModelOption? {
        status.models.first { $0.needsDownload && !$0.needsToken }
    }

    /// *Understand what you mean*. A download outranks everything, then its failure (while still missing), then the
    /// background re-read and a pending switch, then what this memory searches with now. Sleep running disables the
    /// button and says why: a switch is refused while any run goes (`ProjectWriteGate.sleepRunning`).
    static func meaning(_ status: EmbeddingsStatus?, sleeping: Bool) -> UnderstandRow? {
        guard let status else { return nil }
        let install = status.install
        let sharper = sharper(status)
        if install.isInstalling, !install.isVision {
            return UnderstandRow(detail: install.step.isEmpty ? Copy.SearchFiles.gettingReady : Copy.SearchFiles.downloading(install.step),
                                 busy: true, done: install.done, total: install.total)
        }
        if install.state == "failed", !install.error.isEmpty,
           install.part == EmbeddingInstallState.partText || install.part.isEmpty,
           let sharper, !sharper.available {
            return gated(UnderstandRow(detail: install.error, failed: true, button: Copy.SearchFiles.tryAgain,
                                       action: .fetchMeaning(sharper.id), help: Copy.SearchFiles.meaningTurnOnHelp),
                         sleeping: sleeping, downloading: install.isInstalling)
        }
        let reindex = status.reindex
        if reindex.state == "running" {
            return UnderstandRow(detail: Copy.SearchFiles.rereading(done: reindex.done, total: reindex.total), busy: true)
        }
        if reindex.state == "waiting" { return UnderstandRow(detail: Copy.SearchFiles.waitsForSleep) }
        // Review B2 — the backend's sentence here can be a health diagnostic (a hosted service, a dev command); the
        // default view says it in its own words. Advanced's line keeps the backend's detail.
        if reindex.state == "failed", status.nextModel != status.model {
            return UnderstandRow(detail: Copy.SearchFiles.rereadFailed, failed: true)
        }
        if !status.nextModel.isEmpty, status.nextModel != status.model {
            return UnderstandRow(detail: Copy.SearchFiles.switchesAtNextSleep)
        }
        guard let current = status.option(status.model) else { return UnderstandRow(detail: Copy.SearchFiles.meaningOther) }
        if current.needsDownload, !current.available {
            // Built elsewhere with a downloaded version: its vectors are kept, search reads words until it's here.
            if current.needsToken { return UnderstandRow(detail: Copy.SearchFiles.meaningMissingLarger) }
            return gated(UnderstandRow(detail: Copy.SearchFiles.meaningMissing(bytes: current.downloadBytes),
                                       button: Copy.SearchFiles.download, action: .fetchMeaning(current.id),
                                       help: Copy.SearchFiles.meaningTurnOnHelp), sleeping: sleeping, downloading: install.isInstalling)
        }
        if current.needsDownload {
            return UnderstandRow(detail: current.needsToken ? Copy.SearchFiles.meaningLarger : Copy.SearchFiles.meaningSharper,
                                 on: true)
        }
        if let sharper {
            if !sharper.available {
                return gated(UnderstandRow(detail: Copy.SearchFiles.meaningOffer(bytes: sharper.downloadBytes),
                                           button: Copy.SearchFiles.turnOn, action: .fetchMeaning(sharper.id),
                                           help: Copy.SearchFiles.meaningTurnOnHelp), sleeping: sleeping, downloading: install.isInstalling)
            }
            return gated(UnderstandRow(detail: Copy.SearchFiles.meaningReadyHere, button: Copy.SearchFiles.turnOn,
                                       action: .chooseMeaning(sharper.id), help: Copy.SearchFiles.meaningUseHelp),
                         sleeping: sleeping, downloading: install.isInstalling)
        }
        return UnderstandRow(detail: Copy.SearchFiles.meaningBuiltIn, on: true)
    }

    /// *Understand images* — its own second click. Hidden (nil) when the backend doesn't say; on an unsupported Mac a
    /// fact with no button; disabled until the text part is on this Mac, so the two clicks stay two clicks.
    static func images(_ status: EmbeddingsStatus?) -> UnderstandRow? {
        guard let status, let vision = status.vision else { return nil }
        let install = status.install
        if !vision.supported { return UnderstandRow(detail: Copy.SearchFiles.imagesUnsupported) }
        if install.isInstalling, install.isVision {
            return UnderstandRow(detail: install.step.isEmpty ? Copy.SearchFiles.gettingReady : Copy.SearchFiles.downloading(install.step),
                                 busy: true, done: install.done, total: install.total)
        }
        if vision.installed { return UnderstandRow(detail: Copy.SearchFiles.imagesOn, on: true) }
        if install.state == "failed", install.isVision, !install.error.isEmpty {
            return UnderstandRow(detail: install.error, failed: true, button: Copy.SearchFiles.tryAgain,
                                 action: .fetchImages, help: Copy.SearchFiles.imagesTurnOnHelp)
        }
        if install.isInstalling {
            return UnderstandRow(detail: Copy.SearchFiles.imagesWaitsForDownload, button: Copy.SearchFiles.turnOn,
                                 action: .fetchImages, enabled: false, help: Copy.SearchFiles.imagesWaitsForDownloadHelp)
        }
        let textHere = sharper(status)?.available ?? !vision.includesText
        if !textHere || vision.includesText {
            return UnderstandRow(detail: Copy.SearchFiles.imagesWaitsForMeaning, button: Copy.SearchFiles.turnOn,
                                 action: .fetchImages, enabled: false, help: Copy.SearchFiles.imagesWaitsHelp)
        }
        return UnderstandRow(detail: Copy.SearchFiles.imagesOffer(bytes: vision.downloadBytes), button: Copy.SearchFiles.turnOn,
                             action: .fetchImages, help: Copy.SearchFiles.imagesTurnOnHelp)
    }

    /// Sleep running, or another download (the image part, or the Looks shortcut fetching both) already going: the
    /// button stays, dimmed, and says why (DR-41) — never an enabled click that answers 409.
    private static func gated(_ row: UnderstandRow, sleeping: Bool, downloading: Bool = false) -> UnderstandRow {
        guard sleeping || downloading, row.action != nil else { return row }
        var row = row
        row.enabled = false
        row.help = sleeping ? Copy.SearchFiles.sleepRunningHelp : Copy.SearchFiles.downloadRunningHelp
        return row
    }
}
