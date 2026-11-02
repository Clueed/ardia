import Foundation

final class GatewayScope {
  private static let probeDeadline: TimeInterval = 3

  private let queue: DispatchQueue
  private var contextOfKey: [String: String] = [:]
  private var contexts: [String: String] = [:]
  private var monitor: GatewayUpstream?
  private var nextId = 0

  init(queue: DispatchQueue) {
    self.queue = queue
  }

  func start(engine: GatewayEngine) {
    stop()
    guard let url = engine.url(path: engine.browser) else { return }
    let monitor = GatewayUpstream(url: url, queue: queue)
    self.monitor = monitor
    monitor.onText = { [weak self] text in self?.observe(text) }
    monitor.onClose = { [weak self, weak monitor] in
      guard let self, self.monitor === monitor else { return }
      self.monitor = nil
    }
    monitor.start()
    send(monitor, "Target.setDiscoverTargets", ["discover": true])
    send(monitor, "Target.getTargets", [:])
  }

  func stop() {
    monitor?.close()
    monitor = nil
    contexts = [:]
    contextOfKey = [:]
  }

  func contextOf(target: String) -> String? { contexts[target] }

  func isOpen(_ target: String) -> Bool { contexts[target] != nil }

  func inScope(target: String, key: String) -> Bool {
    guard let context = contexts[target], let mine = contextOfKey[key] else { return false }
    return context == mine
  }

  func inScope(info: [String: Any], key: String) -> Bool {
    guard let target = info["targetId"] as? String else { return false }
    if let context = info["browserContextId"] as? String {
      contexts[target] = context
      return contextOfKey[key] == context
    }
    return inScope(target: target, key: key)
  }

  func learn(target: String, info: [String: Any], key: String) {
    guard let context = info["browserContextId"] as? String else { return }
    contexts[target] = context
    contextOfKey[key] = context
  }

  func ensure(key: String, done: @escaping () -> Void) {
    if contextOfKey[key] != nil { return done() }
    var finished = false
    let finish = {
      guard !finished else { return }
      finished = true
      done()
    }
    queue.asyncAfter(deadline: .now() + Self.probeDeadline, execute: finish)
    DispatchQueue.main.async { [weak self] in
      let tabs = ArdiaGatewayTabs.hostedTabs().filter { $0["profile"] == key }.compactMap { $0["tabId"] }
      self?.probe(tabs[...], key: key, done: finish)
    }
  }

  func resolve(tab tabId: String, key: String, done: @escaping (String?) -> Void) {
    DispatchQueue.main.async { [weak self] in
      ArdiaGatewayTabs.target(ofTab: tabId) { info in
        self?.queue.async {
          guard let self, let info, let target = info["targetId"] as? String else { return done(nil) }
          self.learn(target: target, info: info, key: key)
          done(target)
        }
      }
    }
  }

  private func probe(_ tabs: ArraySlice<String>, key: String, done: @escaping () -> Void) {
    guard let tabId = tabs.first else { return queue.async(execute: done) }
    ArdiaGatewayTabs.target(ofTab: tabId) { [weak self] info in
      guard let self else { return }
      if let info, let target = info["targetId"] as? String {
        self.queue.async {
          self.learn(target: target, info: info, key: key)
          done()
        }
        return
      }
      self.probe(tabs.dropFirst(), key: key, done: done)
    }
  }

  private func send(_ upstream: GatewayUpstream, _ method: String, _ params: [String: Any]) {
    nextId += 1
    guard let data = try? JSONSerialization.data(withJSONObject: ["id": nextId, "method": method, "params": params]) else { return }
    upstream.send(String(decoding: data, as: UTF8.self))
  }

  private func observe(_ text: String) {
    guard let message = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { return }
    if let infos = (message["result"] as? [String: Any])?["targetInfos"] as? [[String: Any]] {
      for info in infos { record(info) }
      return
    }
    let params = message["params"] as? [String: Any] ?? [:]
    switch message["method"] as? String {
    case "Target.targetCreated", "Target.targetInfoChanged":
      if let info = params["targetInfo"] as? [String: Any] { record(info) }
    case "Target.targetDestroyed":
      if let target = params["targetId"] as? String { contexts[target] = nil }
    default:
      break
    }
  }

  private func record(_ info: [String: Any]) {
    guard let target = info["targetId"] as? String, let context = info["browserContextId"] as? String else { return }
    contexts[target] = context
  }
}
