import Foundation

struct GatewayEngine {
  let port: Int
  let browser: String
  let token: String

  static func read(chromiumDirectory: String) -> GatewayEngine? {
    let path = (chromiumDirectory as NSString).appendingPathComponent("ArdiaControl.json")
    var info = stat()
    guard lstat(path, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(), info.st_mode & 0o777 == 0o600 else { return nil }
    let descriptor = open(path, O_RDONLY | O_NOFOLLOW)
    guard descriptor >= 0 else { return nil }
    let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    guard let data = try? handle.readToEnd(), data.count < 1 << 16,
      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
      let port = json["port"] as? Int, port > 0, port < 65536,
      let browser = json["browser"] as? String, browser.hasPrefix("/devtools/browser/"),
      let token = json["token"] as? String, !token.isEmpty,
      let pid = json["pid"] as? Int, pid == Int(getpid())
    else { return nil }
    return GatewayEngine(port: port, browser: browser, token: token)
  }

  func url(path: String) -> URL? {
    var components = URLComponents()
    components.scheme = "ws"
    components.host = "127.0.0.1"
    components.port = port
    components.percentEncodedPath = path
    components.queryItems = [URLQueryItem(name: "token", value: token)]
    return components.url
  }
}
