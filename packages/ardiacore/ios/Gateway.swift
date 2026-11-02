import AppKit
import Foundation
import Network

final class Gateway {
  static let shared = Gateway()

  private static let requestLifetime: TimeInterval = 120
  private static let idleLimit: TimeInterval = 30 * 60
  private static let openDeadline: TimeInterval = 10
  private static let maxPending = 16
  private static let maxOpensPerSession = 4
  private static let fileName = "ArdiaGateway.json"

  let queue = DispatchQueue(label: "ardia.gateway")
  private lazy var server = GatewayServer(queue: queue)
  private lazy var scope = GatewayScope(queue: queue)
  private var running = false
  private var starting = false
  private var generation = 0
  private var lateOpens: [String: String] = [:]
  private var controlToken = ""
  private var browserPath = ""
  private var timer: DispatchSourceTimer?
  private var profiles: [GatewayProfile] = []
  private var shownTabs: [String: String] = [:]
  private var requests: [String: GatewayConnect] = [:]
  private var sessions: [GatewaySession] = []
  private var opens: [String: (session: GatewaySession, deadline: Date, done: (String?) -> Void)] = [:]
  private var quitObserver: NSObjectProtocol?

  private var chromiumDirectory: String { ArdiaHost.dataDirectory }
  private var filePath: String { ((chromiumDirectory as NSString).deletingLastPathComponent as NSString).appendingPathComponent(Self.fileName) }

  func start(completion: @escaping ([String: Any]) -> Void) {
    queue.async { [self] in
      if running { return completion(status()) }
      if starting { return completion(["state": "off", "reason": "already starting"]) }
      guard let engine = GatewayEngine.read(chromiumDirectory: chromiumDirectory) else { return completion(["state": "off", "reason": "the engine's control server isn't on"]) }
      generation += 1
      let attempt = generation
      starting = true
      server.onRequest = { [weak self] request, connection in self?.handle(request, connection) }
      server.start { [self] port in
        guard attempt == generation, starting else { return completion(["state": "off", "reason": "stopped while starting"]) }
        starting = false
        guard let port else {
          server.stop()
          return completion(["state": "off", "reason": "couldn't listen"])
        }
        running = true
        controlToken = GatewayTokens.random()
        browserPath = "/devtools/browser/" + UUID().uuidString
        guard writeFile(port: port) else {
          stopNow()
          return completion(["state": "off", "reason": "couldn't write \(Self.fileName)"])
        }
        scope.start(engine: engine) { [weak self] in
          guard let self else { return nil }
          return GatewayEngine.read(chromiumDirectory: self.chromiumDirectory)
        }
        startTimer()
        watchQuit()
        completion(status())
      }
    }
  }

  func stop(completion: (() -> Void)? = nil) {
    queue.async { [self] in
      generation += 1
      starting = false
      stopNow()
      completion?()
    }
  }

  func status() -> [String: Any] {
    running ? ["state": "on", "port": Int(server.port)] : ["state": "off"]
  }

  func setProfiles(_ list: [[String: Any]]) {
    queue.async { [self] in
      profiles = list.compactMap { item in
        guard let id = item["id"] as? String, let key = item["key"] as? String, let name = item["name"] as? String else { return nil }
        return GatewayProfile(id: id, key: key, name: name, kind: item["kind"] as? String == "agent" ? "agent" : "real")
      }
      let gone = sessions.filter { session in !profiles.contains { $0.id == session.profileId } }
      for session in gone { end(session, announce: false) }
      if !gone.isEmpty { announceSessions() }
    }
  }

  func setShownTabs(_ tabs: [String: Any]) {
    queue.async { [self] in shownTabs = tabs.compactMapValues { $0 as? String } }
  }

  func reply(request: String, allow: Bool, profile: String) {
    queue.async { [self] in
      guard var connect = requests[request], connect.state == .pending else { return }
      connect.settledAt = Date()
      if allow, let chosen = profiles.first(where: { $0.id == profile }),
        connect.newName == nil ? connect.profileId == profile : chosen.kind == "agent" && GatewayNames.same(chosen.name, connect.newName ?? "") {
        let session = GatewaySession(token: GatewayTokens.random(), id: GatewayTokens.random(bytes: 6), profile: chosen, agent: connect.agent)
        sessions.append(session)
        connect.state = .allowed
        connect.session = session
        requests[request] = connect
        announceSessions()
      } else {
        connect.state = .denied
        requests[request] = connect
      }
    }
  }

  func endSessions(profile: String) {
    queue.async { [self] in
      let ending = sessions.filter { $0.profileId == profile }
      for session in ending { end(session, announce: false) }
      if !ending.isEmpty { announceSessions() }
    }
  }

  func tabOpened(request: String, tabId: String?) {
    queue.async { [self] in
      guard let open = opens.removeValue(forKey: request) else {
        if let tabId, let profile = lateOpens.removeValue(forKey: request) { emit("gateway.closeTab", ["tabId": tabId, "profile": profile]) }
        return
      }
      guard let tabId else { return open.done(nil) }
      resolveTab(tabId, key: open.session.key, until: open.deadline) { [weak self] target in
        if target == nil { self?.emit("gateway.closeTab", ["tabId": tabId, "profile": open.session.profileId]) }
        open.done(target)
      }
    }
  }

  private func stopNow() {
    server.stop()
    guard running else { return }
    running = false
    for session in sessions { session.end() }
    sessions = []
    for (id, connect) in requests where connect.state == .pending { emit("gateway.connectCancel", ["request": id]) }
    requests = [:]
    for open in opens.values { open.done(nil) }
    opens = [:]
    lateOpens = [:]
    timer?.cancel()
    timer = nil
    scope.stop()
    server.stop()
    unlink(filePath)
    announceSessions()
  }

  private func watchQuit() {
    guard quitObserver == nil else { return }
    quitObserver = NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil, queue: nil) { [weak self] _ in
      self?.queue.sync { self?.stopNow() }
    }
  }

  private func writeFile(port: UInt16) -> Bool {
    let body: [String: Any] = ["port": Int(port), "browser": browserPath, "token": controlToken, "pid": Int(getpid()), "generation": Int(Date().timeIntervalSince1970 * 1000)]
    guard let data = try? JSONSerialization.data(withJSONObject: body) else { return false }
    let temp = filePath + ".\(getpid()).tmp"
    unlink(temp)
    let descriptor = open(temp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
    guard descriptor >= 0 else { return false }
    let written = data.withUnsafeBytes { write(descriptor, $0.baseAddress, data.count) }
    let secured = fchmod(descriptor, 0o600) == 0
    let closed = close(descriptor) == 0
    guard written == data.count, secured, closed, Darwin.rename(temp, filePath) == 0 else {
      unlink(temp)
      return false
    }
    return true
  }

  private func startTimer() {
    let timer = DispatchSource.makeTimerSource(queue: queue)
    timer.schedule(deadline: .now() + 1, repeating: 1)
    timer.setEventHandler { [weak self] in self?.tick() }
    timer.resume()
    self.timer = timer
  }

  private func tick() {
    let now = Date()
    for (id, connect) in requests {
      switch connect.state {
      case .pending where now.timeIntervalSince(connect.created) > Self.requestLifetime:
        requests[id] = nil
        emit("gateway.connectCancel", ["request": id])
      case .allowed where now.timeIntervalSince(connect.settledAt ?? now) > Self.requestLifetime:
        requests[id] = nil
        if let session = connect.session, !session.polled { end(session) }
      case .denied where now.timeIntervalSince(connect.settledAt ?? now) > Self.requestLifetime:
        requests[id] = nil
      default:
        break
      }
    }
    let idle = sessions.filter { now.timeIntervalSince($0.lastActive) > Self.idleLimit }
    for session in idle { end(session, announce: false) }
    if !idle.isEmpty { announceSessions() }
  }

  private func end(_ session: GatewaySession, announce: Bool = true) {
    sessions.removeAll { $0 === session }
    session.end()
    if announce { announceSessions() }
  }

  private func announceSessions() {
    emit("gateway.sessions", ["sessions": sessions.map { ["id": $0.id, "profile": $0.profileId, "agent": $0.agent] }])
  }

  private func emit(_ name: String, _ data: [String: Any]) {
    DispatchQueue.main.async { ArdiaEvents.emit(name, data: data) }
  }

  private func handle(_ request: GatewayRequest, _ connection: NWConnection) {
    let port = server.port
    guard request.headers["origin"] == nil, let host = request.headers["host"], host == "127.0.0.1:\(port)" || host == "localhost:\(port)" else {
      return GatewayServer.respond(connection, status: 403, json: ["error": "forbidden"])
    }
    guard request.method == "GET" else { return GatewayServer.respond(connection, status: 405, json: ["error": "bad-request"]) }
    if request.wantsSocket { return openSocket(request, connection) }
    route(request) { status, body in GatewayServer.respond(connection, status: status, json: body) }
  }

  private func route(_ request: GatewayRequest, reply: @escaping (Int, Any) -> Void) {
    let token = request.query["token"] ?? ""
    let control = GatewayTokens.equal(token, controlToken)
    let session = control ? nil : sessions.first { GatewayTokens.equal(token, $0.token) }
    session?.touch()
    switch (request.path, control, session) {
    case ("/ardia/profiles", true, _):
      reply(200, ["profiles": profiles.map { profile in ["name": profile.name, "kind": profile.kind, "connected": sessions.filter { $0.profileId == profile.id }.count] }])
    case ("/ardia/connect", true, _):
      connect(request.query, reply: reply)
    case ("/ardia/active", false, let session?):
      active(session) { target in reply(200, ["targetId": target.map { $0 as Any } ?? NSNull()]) }
    case ("/ardia/disconnect", false, let session?):
      end(session)
      reply(200, [String: Any]())
    case ("/ardia/rename", false, let session?):
      rename(session, request.query["name"], reply: reply)
    default:
      reply(404, ["error": "not-found"])
    }
  }

  private func connect(_ query: [String: String], reply: (Int, Any) -> Void) {
    if let id = query["request"] {
      guard let connect = requests[id] else { return reply(200, ["state": "expired"]) }
      if query["cancel"] == "1" {
        requests[id] = nil
        if connect.state == .pending { emit("gateway.connectCancel", ["request": id]) }
        if let session = connect.session, !session.polled { end(session) }
        return reply(200, [String: Any]())
      }
      switch connect.state {
      case .pending:
        return reply(200, ["state": "pending"])
      case .denied:
        requests[id] = nil
        return reply(200, ["state": "denied"])
      case .allowed:
        requests[id] = nil
        guard let session = connect.session, sessions.contains(where: { $0 === session }) else { return reply(200, ["state": "expired"]) }
        session.polled = true
        session.touch()
        let name = profiles.first { $0.id == session.profileId }?.name ?? ""
        return reply(200, ["state": "allowed", "session": session.token, "profile": name, "kind": session.kind])
      }
    }
    guard requests.values.filter({ $0.state == .pending }).count < Self.maxPending else { return reply(429, ["error": "too-many-requests"]) }
    let agent = GatewayNames.valid(query["agent"]) ?? "agent"
    let id = GatewayTokens.random(bytes: 16)
    if query["new"] != nil {
      guard let name = GatewayNames.valid(query["new"]) else { return reply(400, ["error": "bad-name"]) }
      let pendingNames = requests.values.filter { $0.state == .pending }.compactMap(\.newName)
      if profiles.contains(where: { GatewayNames.same($0.name, name) }) || pendingNames.contains(where: { GatewayNames.same($0, name) }) {
        return reply(409, ["error": "name-taken"])
      }
      requests[id] = GatewayConnect(agent: agent, profileId: nil, newName: name)
      emit("gateway.connectRequest", ["request": id, "agent": agent, "new": name])
      return reply(200, ["request": id])
    }
    guard let name = GatewayNames.valid(query["profile"]) else { return reply(400, ["error": "bad-name"]) }
    guard let profile = profiles.first(where: { $0.name == name }) ?? profiles.first(where: { GatewayNames.same($0.name, name) }) else {
      return reply(404, ["error": "no-such-profile"])
    }
    requests[id] = GatewayConnect(agent: agent, profileId: profile.id, newName: nil)
    emit("gateway.connectRequest", ["request": id, "agent": agent, "profile": profile.id])
    reply(200, ["request": id])
  }

  private func rename(_ session: GatewaySession, _ raw: String?, reply: (Int, Any) -> Void) {
    guard session.kind == "agent" else { return reply(403, ["error": "not-agent"]) }
    guard let name = GatewayNames.valid(raw) else { return reply(400, ["error": "bad-name"]) }
    if profiles.contains(where: { $0.id != session.profileId && GatewayNames.same($0.name, name) }) { return reply(409, ["error": "name-taken"]) }
    if let index = profiles.firstIndex(where: { $0.id == session.profileId }) { profiles[index].name = name }
    emit("gateway.rename", ["profile": session.profileId, "name": name])
    reply(200, [String: Any]())
  }

  private func active(_ session: GatewaySession, done: @escaping (String?) -> Void) {
    let fallback = { [self] in done(session.created.last { scope.isOpen($0) }) }
    guard let tabId = shownTabs[session.profileId] else { return fallback() }
    scope.resolve(tab: tabId, key: session.key) { target in target.map(done) ?? fallback() }
  }

  private func openTab(_ session: GatewaySession, _ url: String, _ background: Bool, _ done: @escaping (String?) -> Void) -> Bool {
    guard opens.values.filter({ $0.session === session }).count < Self.maxOpensPerSession else { return false }
    let id = GatewayTokens.random(bytes: 12)
    opens[id] = (session, Date().addingTimeInterval(Self.openDeadline), done)
    queue.asyncAfter(deadline: .now() + Self.openDeadline) { [weak self] in
      guard let self, let open = self.opens.removeValue(forKey: id) else { return }
      self.lateOpens[id] = open.session.profileId
      open.done(nil)
      self.queue.asyncAfter(deadline: .now() + Self.requestLifetime) { self.lateOpens[id] = nil }
    }
    emit("gateway.openTab", ["request": id, "profile": session.profileId, "url": url, "background": background])
    return true
  }

  private func resolveTab(_ tabId: String, key: String, until deadline: Date, done: @escaping (String?) -> Void) {
    scope.resolve(tab: tabId, key: key) { [weak self] target in
      if let target { return done(target) }
      guard let self, Date() < deadline else { return done(nil) }
      self.queue.asyncAfter(deadline: .now() + 0.15) { self.resolveTab(tabId, key: key, until: deadline, done: done) }
    }
  }

  private func openSocket(_ request: GatewayRequest, _ connection: NWConnection) {
    let token = request.query["token"] ?? ""
    guard let session = sessions.first(where: { GatewayTokens.equal(token, $0.token) }), let engine = GatewayEngine.read(chromiumDirectory: chromiumDirectory) else {
      return GatewayServer.respond(connection, status: 404, json: ["error": "not-found"])
    }
    session.touch()
    let pagePrefix = "/devtools/page/"
    let page: String? = request.path.hasPrefix(pagePrefix) ? String(request.path.dropFirst(pagePrefix.count)) : nil
    guard page != nil || request.path == browserPath else { return GatewayServer.respond(connection, status: 404, json: ["error": "not-found"]) }
    if let page, page.isEmpty || page.contains("/") { return GatewayServer.respond(connection, status: 404, json: ["error": "not-found"]) }
    scope.ensure(key: session.key) { [self] in
      guard sessions.contains(where: { $0 === session }) else { return GatewayServer.respond(connection, status: 404, json: ["error": "not-found"]) }
      if let page, !scope.inScope(target: page, key: session.key) { return GatewayServer.respond(connection, status: 403, json: ["error": "out-of-scope"]) }
      guard let url = engine.url(path: page.map { pagePrefix + $0 } ?? engine.browser), GatewayServer.upgrade(connection, request) else {
        return GatewayServer.respond(connection, status: 400, json: ["error": "bad-request"])
      }
      let client = GatewaySocket(connection: connection, leftover: request.leftover)
      let upstream = GatewayUpstream(url: url, queue: queue)
      let proxy = GatewayProxy(session: session, client: client, upstream: upstream, scope: scope, page: page) { [weak self] session, url, background, done in
        self?.openTab(session, url, background, done) ?? false
      }
      proxy.onClose = { [weak proxy] in session.proxies.removeAll { $0 === proxy } }
      session.proxies.append(proxy)
      proxy.start()
    }
  }
}
