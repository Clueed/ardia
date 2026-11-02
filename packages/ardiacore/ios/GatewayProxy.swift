import Foundation

final class GatewayProxy {
  typealias Opener = (_ session: GatewaySession, _ url: String, _ background: Bool, _ done: @escaping (String?) -> Void) -> Bool

  private struct Pending {
    let clientId: Any?
    let method: String
    let target: String?
  }

  private static let contextMethods: Set<String> = ["Target.getBrowserContexts", "Target.createBrowserContext", "Target.disposeBrowserContext"]

  private weak var session: GatewaySession?
  private let key: String
  private let client: GatewaySocket
  private let upstream: GatewayUpstream
  private let scope: GatewayScope
  private let open: Opener
  private var pending: [Int: Pending] = [:]
  private var nextId = 0
  private var shown: Set<String> = []
  private var children: [String: String] = [:]
  private var closed = false
  var onClose: (() -> Void)?

  init(session: GatewaySession, client: GatewaySocket, upstream: GatewayUpstream, scope: GatewayScope, page: String?, open: @escaping Opener) {
    self.session = session
    self.key = session.key
    self.client = client
    self.upstream = upstream
    self.scope = scope
    self.open = open
    if let page { shown.insert(page) }
  }

  func start() {
    client.onText = { [weak self] text in self?.fromClient(text) }
    client.onClose = { [weak self] in self?.close() }
    upstream.onText = { [weak self] text in self?.fromUpstream(text) }
    upstream.onClose = { [weak self] in self?.close() }
    upstream.start()
    client.start()
  }

  func close() {
    guard !closed else { return }
    closed = true
    client.close()
    upstream.close()
    let done = onClose
    onClose = nil
    done?()
  }

  private func fromClient(_ text: String) {
    session?.touch()
    guard var message = Self.object(text), let id = message["id"] else { return }
    let method = message["method"] as? String ?? ""
    let child = message["sessionId"] as? String
    let params = message["params"] as? [String: Any] ?? [:]
    if let child, children[child] == nil { return refuse(id, child, "\(method) in that session") }
    if method == "Target.createTarget" { return create(id, child, params) }
    if Self.contextMethods.contains(method) { return refuse(id, child, method) }
    if let target = params["targetId"] as? String, !scope.inScope(target: target, key: key) { return refuse(id, child, "\(method) on that target") }
    if let other = params["sessionId"] as? String, children[other] == nil { return refuse(id, child, "\(method) on that session") }
    nextId += 1
    pending[nextId] = Pending(clientId: id, method: method, target: params["targetId"] as? String)
    message["id"] = nextId
    send(upstream: message)
  }

  private func fromUpstream(_ text: String) {
    session?.touch()
    guard var message = Self.object(text) else { return }
    if let upstreamId = message["id"] as? Int {
      guard let request = pending.removeValue(forKey: upstreamId), let clientId = request.clientId else { return }
      message["id"] = clientId
      if var result = message["result"] as? [String: Any] {
        switch request.method {
        case "Target.getTargets":
          let infos = (result["targetInfos"] as? [[String: Any]] ?? []).filter { scope.inScope(info: $0, key: key) }
          for info in infos { if let target = info["targetId"] as? String { shown.insert(target) } }
          result["targetInfos"] = infos
          message["result"] = result
        case "Target.attachToTarget":
          if let child = result["sessionId"] as? String, let target = request.target { children[child] = target }
        case "Target.getTargetInfo":
          if let info = result["targetInfo"] as? [String: Any], info["type"] as? String != "browser", !scope.inScope(info: info, key: key) {
            return refuse(clientId, message["sessionId"] as? String, "Target.getTargetInfo on that target")
          }
        default:
          break
        }
      }
      return send(client: message)
    }
    guard let method = message["method"] as? String else { return }
    let parent = message["sessionId"] as? String
    if let parent, children[parent] == nil { return }
    let params = message["params"] as? [String: Any] ?? [:]
    switch method {
    case "Target.targetCreated", "Target.targetInfoChanged":
      guard let info = params["targetInfo"] as? [String: Any], let target = info["targetId"] as? String, scope.inScope(info: info, key: key) else { return }
      shown.insert(target)
    case "Target.attachedToTarget":
      guard let info = params["targetInfo"] as? [String: Any], let target = info["targetId"] as? String, let child = params["sessionId"] as? String else { return }
      guard scope.inScope(info: info, key: key) else { return detach(child, parent: parent) }
      children[child] = target
      shown.insert(target)
    case "Target.detachedFromTarget":
      guard let child = params["sessionId"] as? String, children.removeValue(forKey: child) != nil else { return }
    case "Target.targetDestroyed", "Target.targetCrashed":
      guard let target = params["targetId"] as? String, shown.contains(target) else { return }
      if method == "Target.targetDestroyed" { shown.remove(target) }
    default:
      break
    }
    client.send(text)
  }

  private func create(_ id: Any, _ child: String?, _ params: [String: Any]) {
    guard child == nil, let session else { return refuse(id, child, "Target.createTarget there") }
    if params["browserContextId"] != nil { return refuse(id, child, "Target.createTarget in another browser context") }
    if params["forTab"] != nil { return refuse(id, child, "Target.createTarget for a tab") }
    guard let url = Self.destination(params["url"]) else { return refuse(id, child, "Target.createTarget to that URL") }
    let background = session.kind == "agent" || params["background"] as? Bool != false
    let accepted = open(session, url, background) { [weak self] target in
      guard let self, !self.closed else { return }
      guard let target else { return self.refuse(id, nil, "Target.createTarget", reason: "the tab didn't open in time") }
      guard self.scope.inScope(target: target, key: self.key) else { return self.refuse(id, nil, "Target.createTarget", reason: "the tab opened outside this session's profile") }
      self.shown.insert(target)
      self.session?.created.append(target)
      self.send(client: ["id": id, "result": ["targetId": target]])
    }
    if !accepted { refuse(id, nil, "Target.createTarget", reason: "too many tabs are opening at once") }
  }

  private func detach(_ child: String, parent: String?) {
    nextId += 1
    pending[nextId] = Pending(clientId: nil, method: "Target.detachFromTarget", target: nil)
    var message: [String: Any] = ["id": nextId, "method": "Target.detachFromTarget", "params": ["sessionId": child]]
    if let parent { message["sessionId"] = parent }
    send(upstream: message)
  }

  private func refuse(_ id: Any, _ child: String?, _ what: String, reason: String? = nil) {
    let text = reason.map { "ardia: \($0)" } ?? "ardia: \(what) is outside this session's profile"
    var message: [String: Any] = ["id": id, "error": ["code": -32000, "message": text]]
    if let child { message["sessionId"] = child }
    send(client: message)
  }

  private func send(upstream message: [String: Any]) {
    guard let text = Self.text(message) else { return }
    upstream.send(text)
  }

  private func send(client message: [String: Any]) {
    guard let text = Self.text(message) else { return }
    client.send(text)
  }

  static func destination(_ value: Any?) -> String? {
    guard let raw = (value as? String) ?? (value == nil ? "" : nil) else { return nil }
    if raw.isEmpty || raw == "about:blank" { return "about:blank" }
    guard let url = URL(string: raw), let scheme = url.scheme?.lowercased() else { return nil }
    switch scheme {
    case "http", "https", "data":
      return raw
    case "blob":
      let inner = String(raw.dropFirst("blob:".count)).lowercased()
      return inner.hasPrefix("http://") || inner.hasPrefix("https://") ? raw : nil
    default:
      return nil
    }
  }

  private static func object(_ text: String) -> [String: Any]? {
    try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any]
  }

  private static func text(_ message: [String: Any]) -> String? {
    guard let data = try? JSONSerialization.data(withJSONObject: message) else { return nil }
    return String(decoding: data, as: UTF8.self)
  }
}
