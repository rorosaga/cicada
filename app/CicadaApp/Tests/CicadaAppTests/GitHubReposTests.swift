import XCTest
@testable import CicadaApp

/// G230 — repositories on the graph: the wire's shapes, the Sources panel's decisions and model, the repository card's
/// words. No network: the model runs on `Deps`, every date is passed in with its locale.
@MainActor
final class GitHubReposTests: XCTestCase {
    private let locale = Locale(identifier: "en_US_POSIX")
    private let today = ISODay(year: 2026, month: 11, day: 3)

    private func repo(_ full: String = "bob-example/alpha-project", project: RepoProject? = nil,
                      owned: Bool = true) -> RepoRow {
        RepoRow(id: 501, fullName: full, url: "https://github.com/\(full)", description: "Notes.",
                language: "Python", topics: ["notes"], owned: owned, project: project)
    }

    // MARK: - The wire

    func testTheListsAndTheCardDecodeFromTheBackendsShapes() throws {
        let lists = try JSONDecoder().decode(RepoLists.self, from: Data("""
        {"connected": true,
         "owned": [{"id": 501, "fullName": "bob-example/alpha-project", "url": "https://github.com/bob-example/alpha-project",
                    "private": true, "topics": [], "ownerKind": "User", "archived": false, "fork": false,
                    "starred": false, "owned": true, "added": false,
                    "project": {"project": "alpha", "name": "alpha", "how": "origin"},
                    "projects": [{"project": "alpha", "name": "alpha", "how": "origin"},
                                 {"project": "beta", "name": "Beta", "how": "user"}]}],
         "starred": [{"id": 601, "fullName": "example-org/widget-kit", "starred": true,
                      "starredAt": "2026-09-12T08:30:00+00:00", "entityId": "widget-kit"}]}
        """.utf8))
        XCTAssertTrue(lists.connected)
        XCTAssertEqual(lists.owned.first?.isPrivate, true)
        XCTAssertEqual(lists.owned.first?.project?.isSettled, true)
        XCTAssertEqual(lists.owned.first?.projects.map(\.project), ["alpha", "beta"])
        XCTAssertEqual(lists.starred.first?.url, "https://github.com/example-org/widget-kit")   // derived when absent
        let card = try JSONDecoder().decode(RepositoryDetail.self, from: Data("""
        {"id": 601, "fullName": "example-org/widget-kit", "url": "https://github.com/example-org/widget-kit",
         "entityId": "widget-kit", "ownerKind": "Organization",
         "candidates": [{"project": "kit", "name": "Kit", "how": "name"}, {"project": "z", "name": "Z", "how": "other"}],
         "readme": {"state": "fresh", "text": "# Widget Kit", "truncated": false, "path": "README.md",
                    "fetchedAt": "2026-11-02T10:00:00+00:00"}}
        """.utf8))
        XCTAssertEqual(card.repo.owner, "example-org")
        XCTAssertEqual(card.repo.name, "widget-kit")
        XCTAssertEqual(card.readme.state, "fresh")
        XCTAssertEqual(card.candidates.map(\.project), ["kit", "z"])
        XCTAssertEqual(RepositoryText.candidateLabel(card.candidates[0]), Copy.GitHub.suggested("Kit"))
        XCTAssertEqual(RepositoryText.candidateLabel(card.candidates[1]), "Z")
        let bare = try JSONDecoder().decode(RepositoryDetail.self, from: Data(#"{"fullName": "a-b/c"}"#.utf8))
        XCTAssertEqual(bare.readme.state, "missing")
    }

    // MARK: - The Sources panel

    func testARowSaysItsFlagsAndAtMostTwoProjects() {
        XCTAssertEqual(GitHubReposLogic.detail(repo()), "Python · Notes.")
        var r = repo()
        r.projects = ["a", "b", "c"].map { RepoProject(project: $0, name: $0.uppercased(), how: "user") }
        let shown = GitHubReposLogic.projects(r)
        XCTAssertEqual(shown.shown.map(\.project), ["a", "b"])
        XCTAssertEqual(shown.more, 1)
    }

    func testTheListReadsAgainAndKeepsWhatItHadWhenARefusalComes() async {
        var loads = 0
        var fail = false
        let model = GitHubReposModel(deps: .init(
            fetch: {
                loads += 1
                if fail { throw APIError.httpError(500, "") }
                return RepoLists(connected: true, owned: [self.repo()])
            },
            project: { _, _, _ in RepoProjectResult(project: "", created: false) }))
        await model.load()
        XCTAssertEqual(model.lists.owned.count, 1)
        fail = true
        await model.load()
        XCTAssertEqual(model.lists.owned.count, 1)          // never blank
        XCTAssertEqual(model.note, Copy.GitHub.couldNotRead)
        XCTAssertEqual(loads, 2)
        XCTAssertEqual(GitHubReposModel.describe(APIError.httpError(404, #"{"detail": "Not in memory."}"#)),
                       "Not in memory.")
    }

    // MARK: - Connecting with a code (owner 2026-11-03: "cant we just do oauth? like a connect?")

    private func code(_ interval: Int = 5) -> GitHubConnectCode {
        GitHubConnectCode(userCode: "ABCD-1234", verificationUri: "https://github.com/login/device",
                          expiresAt: 1_000_900, interval: interval)
    }

    func testTheStepFollowsTheBackendsAnswer() {
        XCTAssertEqual(GitHubConnectStep.from(GitHubConnectStatus(available: false)), .unavailable)
        XCTAssertEqual(GitHubConnectStep.from(GitHubConnectStatus(available: true)), .disconnected)
        XCTAssertEqual(GitHubConnectStep.from(GitHubConnectStatus(available: true, pending: code())), .code(code()))
        XCTAssertEqual(GitHubConnectStep.from(GitHubConnectStatus(
            available: true, connected: true, how: "app", installed: false,
            installUrl: "https://github.com/apps/cicada-memory/installations/new")),
            .install(url: "https://github.com/apps/cicada-memory/installations/new"))
        XCTAssertEqual(GitHubConnectStep.from(GitHubConnectStatus(available: true, connected: true, how: "app",
                                                                  installed: true)), .connected(byToken: false))
        XCTAssertEqual(GitHubConnectStep.from(GitHubConnectStatus(available: false, connected: true, how: "token")),
                       .connected(byToken: true))
        XCTAssertEqual(GitHubConnectStep.minutesLeft(code(), now: 1_000_000), 15)
    }

    func testConnectShowsTheCodeOpensGitHubAndWaitsForTheApproval() async {
        var opened: [URL] = []
        var polls = [GitHubConnectPoll(state: "pending", interval: 10),
                     GitHubConnectPoll(state: "connected", status: GitHubConnectStatus(
                        available: true, connected: true, how: "app", installed: false,
                        installUrl: "https://github.com/apps/cicada-memory/installations/new"))]
        var synced = 0
        var installed = false
        let model = GitHubConnectModel(deps: .init(
            status: { GitHubConnectStatus(available: true) },
            start: { self.code() },
            poll: { polls.removeFirst() },
            installation: { GitHubConnectStatus(available: true, connected: true, how: "app", installed: installed) },
            cancel: {},
            sync: { synced += 1; return ConnectorSyncResult(status: "ok", reason: nil, new: 2, seen: 4, error: nil,
                                                            resourcesRead: 0) },
            disconnect: {},
            open: { opened.append($0) },
            sleep: { _ in await Task.yield() }))
        await model.load()
        XCTAssertEqual(model.step, .disconnected)
        await model.connect()
        model.stop()                                         // the test drives the polls itself
        XCTAssertEqual(model.step, .code(code()))
        XCTAssertEqual(opened.map(\.absoluteString), ["https://github.com/login/device"])
        let more = await model.pollOnce()
        XCTAssertTrue(more)
        XCTAssertEqual(model.status.pending?.interval, 10)  // GitHub asked to slow down
        let done = await model.pollOnce()
        XCTAssertFalse(done)
        XCTAssertEqual(model.step, .install(url: "https://github.com/apps/cicada-memory/installations/new"))
        XCTAssertEqual(model.generation, 1)
        model.openInstall()
        XCTAssertEqual(opened.last?.host, "github.com")
        await model.checkInstalled()
        XCTAssertEqual(model.note, Copy.GitHub.notInstalledYet)
        XCTAssertEqual(synced, 0)
        installed = true
        await model.checkInstalled()
        XCTAssertEqual(model.step, .connected(byToken: false))
        XCTAssertEqual(synced, 1)                            // installed: the repositories come in at once
        XCTAssertEqual(model.generation, 2)
    }

    func testACancelledCodeSaysSoAndConnectsNothing() async {
        let model = GitHubConnectModel(deps: .init(
            status: { GitHubConnectStatus(available: true) },
            start: { self.code() },
            poll: { GitHubConnectPoll(state: "denied", words: "You cancelled on GitHub, so nothing was connected.") },
            installation: { GitHubConnectStatus() }, cancel: {},
            sync: { ConnectorSyncResult(status: "ok", reason: nil, new: 0, seen: 0, error: nil, resourcesRead: 0) },
            disconnect: {}, open: { _ in }, sleep: { _ in await Task.yield() }))
        await model.load()
        await model.connect()
        model.stop()
        _ = await model.pollOnce()
        XCTAssertEqual(model.step, .disconnected)
        XCTAssertEqual(model.note, "You cancelled on GitHub, so nothing was connected.")
        XCTAssertEqual(model.generation, 0)
    }

    func testTheWireForConnectingDecodes() throws {
        let status = try JSONDecoder().decode(GitHubConnectStatus.self, from: Data("""
        {"available": true, "connected": false, "grantsUrl": "https://github.com/settings/applications",
         "pending": {"userCode": "ABCD-1234", "verificationUri": "https://github.com/login/device",
                     "expiresAt": 1000900, "interval": 5}}
        """.utf8))
        XCTAssertEqual(status.pending?.userCode, "ABCD-1234")
        let poll = try JSONDecoder().decode(GitHubConnectPoll.self, from: Data(#"{"state": "pending", "interval": 10}"#.utf8))
        XCTAssertEqual(poll.interval, 10)
        let projects = try JSONDecoder().decode(ProjectRepositories.self, from: Data("""
        {"project": "alpha", "repos": [{"id": 501, "fullName": "bob-example/alpha-project", "entityId": "media-a",
                                         "how": "origin"}],
         "candidates": [{"id": 502, "fullName": "bob-example/side-notes", "entityId": "media-b"}]}
        """.utf8))
        XCTAssertEqual(projects.repos.first?.entityId, "media-a")
        XCTAssertEqual(projects.candidates.count, 1)
        XCTAssertFalse(ProjectRepositoriesSection.shows(ProjectRepositories(project: "alpha")))
        XCTAssertTrue(ProjectRepositoriesSection.shows(projects))
        XCTAssertFalse(ProjectRepositoriesSection.shows(nil))
    }

    func testGitHubIsACatalogueAccountRoutedLikeTheTokenConnectors() {
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        XCTAssertEqual(entries.first { $0.id == "github" }?.group, .accounts)
        XCTAssertTrue(ChannelActions.connectorChannels.contains("github"))
        XCTAssertTrue(SourceCatalog.signInChannels.contains("github"))
        XCTAssertEqual(OriginIconography.logoName(for: "github-starred"), "github")
        XCTAssertEqual(OriginIconography.label(for: "github-starred"), "GitHub stars")
    }

    // MARK: - The repository card

    func testTheCardAsksForARepositoryOnlyWhereOneCanBe() {
        XCTAssertTrue(EntityDetailCard.wantsRepositoryDetail(type: .media, media: nil))
        XCTAssertFalse(EntityDetailCard.wantsRepositoryDetail(type: .project, media: nil))   // its own section
        XCTAssertTrue(EntityDetailCard.wantsRepositoryDetail(
            type: .media, media: MediaBlock(url: "https://github.com/a-b/c", mediaType: "repository", kind: "repository")))
        XCTAssertFalse(EntityDetailCard.wantsRepositoryDetail(
            type: .media, media: MediaBlock(url: "https://example.com", mediaType: "url")))
        XCTAssertFalse(EntityDetailCard.wantsRepositoryDetail(type: .person, media: nil))
    }

    func testTheCardSaysWhatThePersonDidAndWhichFlagsHold() {
        XCTAssertEqual(RepositoryText.relation(repo(), today: today, locale: locale), Copy.GitHub.yours)
        XCTAssertEqual(RepositoryText.linkHelp("origin", name: "Alpha"), "Alpha · \(Copy.GitHub.byCheckout)")
        var r = repo(owned: false)
        r.starred = true
        r.starredAt = "2026-09-12T08:30:00+00:00"
        XCTAssertEqual(RepositoryText.relation(r, today: today, locale: locale), "You starred it Sep 12")
        r.starred = false
        r.unstarredOn = "2026-10-30"
        XCTAssertEqual(RepositoryText.relation(r, today: today, locale: locale), "No longer starred since Oct 30")
        r.unstarredOn = nil
        r.added = true
        XCTAssertEqual(RepositoryText.relation(r, today: today, locale: locale), Copy.GitHub.youAdded)
        r.isPrivate = true
        r.archived = true
        XCTAssertEqual(RepositoryText.flags(r), ["Private", "Archived"])
        r.topics = ["a", "b", "c", "d", "e", "f", "g"]
        XCTAssertEqual(RepositoryText.topics(r).shown.count, 5)
        XCTAssertEqual(RepositoryText.topics(r).more, 2)
        XCTAssertEqual(RepositoryText.byline(r), "bob-example · Python")
    }

    func testAKeptSourceSaysItIsReadThroughItsAPI() {
        let source = PageBlocks.Source(ref: "https://github.com/example-org/widget-kit", kind: "url", label: nil,
                                       linkKind: "website", state: "kept", site: "github.com", checkedAt: nil,
                                       addedBy: "user", iconSite: nil)
        XCTAssertEqual(PageWords.state(source, today: today, locale: locale), Copy.Pages.kept)
    }

    func testTheReadmeReadsAsCleanLines() {
        let lines = RepositoryText.lines("# Widget Kit\n\n\n\nA **small** kit of `widgets`.\n\n## Install\n\n```\n"
                                         + "pip install widget-kit\n```\n- one\n* two\n---\n")
        XCTAssertEqual(lines, [
            .heading("Widget Kit", level: 1), .blank, .text("A small kit of widgets."), .blank,
            .heading("Install", level: 2), .blank, .text("pip install widget-kit"), .bullet("one"), .bullet("two"),
        ])
        XCTAssertEqual(RepositoryText.readmeWords(RepositoryReadme(state: "none")), Copy.GitHub.readmeNone)
        XCTAssertEqual(RepositoryText.readmeWords(RepositoryReadme(state: "missing")), Copy.GitHub.readmeMissing)
        XCTAssertNil(RepositoryText.readmeWords(RepositoryReadme(state: "fresh", text: "Hi")))
    }
}
