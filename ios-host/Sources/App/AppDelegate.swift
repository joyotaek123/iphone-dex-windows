import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        if Bundle.main.object(forInfoDictionaryKey: "UIApplicationSceneManifest") == nil {
            let fallbackWindow = UIWindow(frame: UIScreen.main.bounds)
            fallbackWindow.rootViewController = DesktopHostViewController()
            fallbackWindow.makeKeyAndVisible()
            self.window = fallbackWindow
        }
        return true
    }

    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        return UISceneConfiguration(name: "Default Configuration", sessionRole: connectingSceneSession.role)
    }
}
