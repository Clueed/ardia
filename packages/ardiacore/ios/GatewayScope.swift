import Foundation

final class GatewayScope {
  private static let probeDeadline: TimeInterval = 3
  private static let reconnectDelays: [TimeInterval] = [0.5, 1, 2, 5, 10, 30]

  private let queue: DispatchQueue
  private var contextOfKey: [String: String] = [:]
  private var contexts: [String: String] = [:]
  private var tabOfTarget: [String: String] = [:]
  private var monitor: GatewayUpstream?
  private var nextId = 0
  private var engineSource: (() -> GatewayEngine?)?
  private var reconnects = 0
  private var generation = 0

  init(queue: DispatchQueue) {
    self.queue = queue
  }

  func start(engine: GatewayEngine, reread: @escaping () -> GatewayEngine?) {
    stop()
    engineSource = reread
    connect(engine)
  }

  func stop() {
    generation += 1
    engineSource = nil
    reconnects = 0
    monitor?.close()
    monitor = nil
    contexts = [:]
    contextOfKey = [:]
    tabOfTarget = [:]
  }

  private func connect(_ engine: GatewayEngine?) {
    guard let engine, let url = engine.url(path: engine.browser) else { return reconnectLater() }
    let monitor = GatewayUpstream(url: url, queue: queue)
    self.monitor = monitor
    monitor.onOpen = { [weak self] in self?.reconnects = 0 }
    monitor.onText = { [weak self] text in self?.observe(text) }
    monitor.onClose = { [weak self, weak monitor] in
      guard let self, self.monitor === monitor else { return }
      self.monitor = nil
      self.reconnectLater()
    }
    monitor.start()
    send(monitor, "Target.setDiscoverTargets", ["discover": true])
    send(monitor, "Target.getTargets", [:])
  }

  private func reconnectLater() {
    guard engineSource != nil else { return }
    let delay = Self.reconnectDelays[min(reconnects, Self.reconnectDelays.count - 1)]
    reconnects += 1
    let expected = generation
    queue.asyncAfter(deadline: .now() + delay) { [weak self] in
      guard let self, self.generation == expected, self.monitor == nil, let source = self.engineSource else { return }
      self.connect(source())
    }
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

  @discardableResult
  func learn(target: String, info: [String: Any], key: String) -> Bool {
    guard let context = info["browserContextId"] as? String, info["ardiaProfile"] as? String == key else { return false }
    if let known = contextOfKey[key], known != context {
      NSLog("[gateway] a tab reported another browser context for its profile; ignoring it")
      return false
    }
    if contextOfKey.contains(where: { $0.key != key && $0.value == context }) {
      NSLog("[gateway] two profiles reported the same browser context; ignoring it")
      return false
    }
    contexts[target] = context
    contextOfKey[key] = context
    return true
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
          guard let self, let info, let target = info["targetId"] as? String, self.learn(target: target, info: info, key: key) else { return done(nil) }
          done(target)
        }
      }
    }
  }

  func tab(ofTarget target: String, key: String, done: @escaping (String?) -> Void) {
    if let tabId = tabOfTarget[target] { return done(tabId) }
    DispatchQueue.main.async { [weak self] in
      let tabs = ArdiaGatewayTabs.hostedTabs().filter { $0["profile"] == key }.compactMap { $0["tabId"] }
      self?.find(target, in: tabs[...], key: key, done: done)
    }
  }

  private func find(_ target: String, in tabs: ArraySlice<String>, key: String, done: @escaping (String?) -> Void) {
    guard let tabId = tabs.first else { return queue.async { done(nil) } }
    ArdiaGatewayTabs.target(ofTab: tabId) { [weak self] info in
      guard let self else { return }
      let found = info?["targetId"] as? String
      self.queue.async {
        if let found, let info, self.learn(target: found, info: info, key: key) { self.tabOfTarget[found] = tabId }
      }
      if found == target { return self.queue.async { done(tabId) } }
      self.find(target, in: tabs.dropFirst(), key: key, done: done)
    }
  }

  private func probe(_ tabs: ArraySlice<String>, key: String, done: @escaping () -> Void) {
    guard let tabId = tabs.first else { return queue.async(execute: done) }
    ArdiaGatewayTabs.target(ofTab: tabId) { [weak self] info in
      guard let self else { return }
      if let info, let target = info["targetId"] as? String, info["ardiaProfile"] as? String == key {
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
      if let target = params["targetId"] as? String {
        contexts[target] = nil
        tabOfTarget[target] = nil
      }
    default:
      break
    }
  }

  private func record(_ info: [String: Any]) {
    guard let target = info["targetId"] as? String, let context = info["browserContextId"] as? String else { return }
    contexts[target] = context
  }
}
